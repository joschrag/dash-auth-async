"""WebSocket authentication for Dash callbacks.

Single touch-point for the Dash WebSocket internals this package depends on:
the per-app callback executor (``backend._callback_executor``) and the global
``websocket_message`` hook contract. Isolating them here keeps a future Dash
upgrade to one file.
"""

from __future__ import annotations

import asyncio
import contextvars
import secrets
import threading
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from typing import Any
from weakref import WeakKeyDictionary

from .backends import get_active_backend

# Name of the pre-login, browser-stable cookie that ties an anonymous WebSocket
# back to the browser that later authenticates over HTTP. Minted on first
# contact by the auth hook (see the backends' before-request middleware) so it
# is already present at a pre-login WS handshake.
WS_CLIENT_COOKIE = "dac_client"

# The authenticated user (session["user"] dict) for the callback currently being
# dispatched over a WebSocket. Set by the websocket_message hook in the WS
# context and propagated into Dash's callback worker by the context-copying
# executor. ``list_groups`` reads it when no HTTP request context is active.
_WS_AUTH_USER: ContextVar[dict | None] = ContextVar(
    "dash_auth_async_ws_user", default=None
)


class _ContextCopyingExecutor(ThreadPoolExecutor):
    """Run each submitted task inside a copy of the submit-time context.

    Dash's WebSocket runner submits callbacks to a plain ThreadPoolExecutor,
    which does not propagate ``contextvars`` into the worker thread. We pre-seed
    this subclass onto ``backend._callback_executor`` so the ``_WS_AUTH_USER``
    contextvar set by the websocket_message hook reaches the callback worker.
    Each ``submit`` snapshots the context independently, so concurrent callbacks
    stay isolated.
    """

    def submit(self, fn, /, *args, **kwargs):
        ctx = contextvars.copy_context()
        return super().submit(lambda: ctx.run(fn, *args, **kwargs))


# server (Quart/Flask app) -> Auth. Weak keys so test apps are collected.
_AUTH_BY_SERVER: WeakKeyDictionary[Any, Any] = WeakKeyDictionary()

_hook_lock = threading.Lock()
_hook_registered = False


class _WSEntry:
    """A registered anonymous WebSocket plus the loop it runs on."""

    __slots__ = ("loop", "ws")

    def __init__(self, ws: Any, loop: Any) -> None:
        self.ws = ws
        self.loop = loop


# client-id cookie -> the browser's current anonymous (pre-login) socket.
#
# Only *anonymous* sockets are tracked: a login retires those and only those, so
# an already-authenticated socket would only ever bloat the map. And only one
# per browser -- a browser drives a single shared SharedWorker socket, so a
# reconnect replaces the prior entry rather than stacking. Together these bound
# the map to (at most) one entry per distinct pre-login browser.
_WS_BY_CLIENT: dict[str, _WSEntry] = {}
_ws_registry_lock = threading.Lock()


def mint_ws_client_id() -> str:
    """Return a fresh, opaque browser-stable client id for the cookie."""
    return secrets.token_urlsafe(16)


def register_anonymous_ws(client_id: str | None, ws: Any, loop: Any) -> None:
    """Track a browser's current pre-login socket, replacing any stale prior.

    No-op without a client id (e.g. a backend that never minted the cookie):
    such a socket can't be correlated to a later login and falls back to the
    reactive 4401-then-reconnect path.
    """
    if not client_id:
        return
    with _ws_registry_lock:
        _WS_BY_CLIENT[client_id] = _WSEntry(ws, loop)


def close_anonymous_ws(client_id: str | None) -> None:
    """Close the browser's pre-login socket so the renderer reconnects authed.

    Called when ``client_id`` authenticates over HTTP. The close code (``4408``)
    is outside the renderer's no-reconnect set (``1000``/``4001``), so the
    SharedWorker dials a fresh handshake that carries the now-present session
    cookie -- before the user's first click rather than after a sacrificed one.
    Popping the entry also deregisters it, keeping the map from leaking.
    """
    if not client_id:
        return
    with _ws_registry_lock:
        entry = _WS_BY_CLIENT.pop(client_id, None)
    if entry is None:
        return
    _schedule_ws_close(entry.loop, entry.ws)


def _schedule_ws_close(loop: Any, ws: Any) -> None:
    """Schedule ``ws.close`` onto the socket's own event loop, thread-safely.

    The login runs in a separate HTTP task (and possibly thread); a socket can
    only be closed from its own loop, so we hop onto it via
    ``call_soon_threadsafe`` rather than awaiting the close inline.
    """

    async def _safe_close() -> None:
        try:
            await ws.close(code=4408)
        except Exception:  # pylint: disable=broad-exception-caught
            pass  # already closing/closed -- nothing to recover

    try:
        loop.call_soon_threadsafe(lambda: asyncio.ensure_future(_safe_close()))
    except Exception:  # pylint: disable=broad-exception-caught
        pass  # loop gone (socket already torn down) -- nothing to close


def _ws_message_hook(ws: Any, message: Any):
    """Global Dash websocket_message hook: authorize each callback_request.

    The single fail-closed boundary for WebSocket auth: any unexpected error
    while deciding rejects the socket. The decision itself lives in
    ``_authorize_ws_message``.

    Returns:
        A truthy value to allow, or a ``(code, reason)`` tuple to reject
        (which closes the socket).
    """
    if not isinstance(message, dict) or message.get("type") != "callback_request":
        return True
    try:
        return _authorize_ws_message(ws, message)
    except Exception:  # pylint: disable=broad-exception-caught
        # Fail closed on any unexpected error.
        return (4401, "Unauthorized")


def _authorize_ws_message(ws: Any, message: dict) -> bool | tuple[int, str]:
    """Authorize one WebSocket ``callback_request`` for the owning app.

    The owning server and the session user are resolved through the active
    backend's :meth:`Backend.ws_identity` (Quart uses its context globals,
    FastAPI reads ``ws.app``/``ws.session``), keeping this module
    framework-agnostic. Inert for apps that do not use dash-auth-async.

    Returns:
        ``True`` to allow, or a ``(code, reason)`` tuple to reject the socket.
    """
    backend = get_active_backend()
    server, user = backend.ws_identity(ws)
    auth = _AUTH_BY_SERVER.get(server)
    if auth is None:
        # Not a dash-auth-async app: nothing to enforce. Safe because the
        # registry entry is created by the developer's ``Auth(app, ...)`` call,
        # not by the client -- an attacker cannot evict their own app.
        return True
    # Migrate Dash's GLOBAL_CALLBACK_MAP into app.callback_map before Dash
    # validates this request against it -- validation runs *after* the
    # websocket_message hooks return (see _fastapi.py / _quart.py). On FastAPI
    # our auth middleware can short-circuit the page/readiness GET with a 401
    # before Dash's own _setup_server before-hook ever runs, so a WS-first
    # client would otherwise hit an empty map ("Callback function not found").
    # Doing it here is lazy (fires on the first real WS message, after every
    # module-level @callback is registered -- so unlike a construction-time
    # call it never freezes the map early) and idempotent (a self-guarded flag
    # makes every call after the first a single boolean check).
    auth.app._setup_server()
    payload = message.get("payload", {}) or {}
    if auth.authorize_ws(payload, user):
        # Load-bearing invariant: this hook runs before every callback_request
        # is submitted to the executor, so the context-copying executor always
        # snapshots the user set here -- a stale value from a prior message can
        # never reach a worker. ``set`` (never ``reset``) is therefore safe.
        _WS_AUTH_USER.set(user)
        return True
    return (4401, "Unauthorized")


def _ws_connect_hook(ws: Any):
    """Global Dash websocket_connect hook: register the socket by client id.

    Runs at the handshake (before accept) for every socket. Tracks only sockets
    that handshake *anonymously*, keyed by browser (the ``dac_client`` cookie),
    so a later login can retire them; an already-authenticated socket needs no
    retiring and is left untracked. Always allows the connection -- public pages
    legitimately stream over an unauthenticated socket, so this hook must never
    reject.

    Returns:
        ``True`` to allow the connection (bookkeeping never blocks a socket).
    """
    try:
        _track_anonymous_ws(ws)
    except Exception:  # pylint: disable=broad-exception-caught
        pass  # never let bookkeeping block a connection
    return True


def _track_anonymous_ws(ws: Any) -> None:
    """Register ``ws`` if its handshake was anonymous (see ``_ws_connect_hook``)."""
    backend = get_active_backend()
    _, user = backend.ws_identity(ws)
    if user is not None:
        return  # already authenticated -- nothing to retire later
    client_id = getattr(ws, "cookies", {}).get(WS_CLIENT_COOKIE)
    # Resolve the concrete socket: Quart hands us a context-local proxy that
    # can't be closed from the later (different-task) login, so we must keep the
    # underlying object. Starlette's WebSocket has no such proxy and is stored
    # as-is.
    real_ws = ws._get_current_object() if hasattr(ws, "_get_current_object") else ws
    register_anonymous_ws(client_id, real_ws, asyncio.get_running_loop())


def _ensure_hook_registered() -> None:
    """Register the global websocket hooks exactly once per process."""
    global _hook_registered  # noqa: PLW0603 — register the hooks once per process
    with _hook_lock:
        if _hook_registered:
            return
        from dash import hooks  # noqa: PLC0415 — lazy import to avoid an import cycle

        hooks.websocket_message()(_ws_message_hook)
        hooks.websocket_connect()(_ws_connect_hook)
        _hook_registered = True


def enable_ws_auth(auth: Any, app: Any) -> None:
    """Wire WebSocket auth for a dash-auth-async app.

    No-op on backends without WebSocket support (e.g. Flask). For WS-capable
    backends it records the server->Auth mapping, installs the context-copying
    executor (before any dispatch), and registers the global hook once.

    Note Dash's ``callback_map`` is *not* populated here. It is migrated lazily
    on the first WS ``callback_request`` by the message hook (see
    ``_authorize_ws_message``), so a global ``@callback`` registered after
    ``Auth(...)`` is still picked up and the server is never set up twice.
    """
    backend = getattr(app, "backend", None)
    if backend is None or not getattr(backend, "websocket_capability", False):
        return

    _AUTH_BY_SERVER[app.server] = auth

    if not isinstance(
        getattr(backend, "_callback_executor", None), _ContextCopyingExecutor
    ):
        backend._callback_executor = _ContextCopyingExecutor(
            thread_name_prefix="dash-callback-"
        )

    _ensure_hook_registered()
