"""WebSocket authentication for Dash callbacks.

Single touch-point for the Dash WebSocket internals this package depends on:
the per-app callback executor (``backend._callback_executor``) and the global
``websocket_message`` hook contract. Isolating them here keeps a future Dash
upgrade to one file.
"""

from __future__ import annotations

import contextvars
import threading
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from typing import Any
from weakref import WeakKeyDictionary

from .backends import get_active_backend

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

    The owning app and the session user are resolved through the active
    backend's :meth:`Backend.ws_identity` (Quart uses its context globals,
    FastAPI reads ``ws.app``/``ws.session``), keeping this module
    framework-agnostic. Inert for apps that do not use dash-auth-async.

    Returns:
        ``True`` to allow, or a ``(code, reason)`` tuple to reject the socket.
    """
    backend = get_active_backend()
    app, user = backend.ws_identity(ws)
    auth = _AUTH_BY_SERVER.get(app)
    if auth is None:
        # Not a dash-auth-async app: nothing to enforce. Safe because the
        # registry entry is created by the developer's ``Auth(app, ...)`` call,
        # not by the client -- an attacker cannot evict their own app.
        return True
    payload = message.get("payload", {}) or {}
    if auth.authorize_ws(payload, user):
        # Load-bearing invariant: this hook runs before every callback_request
        # is submitted to the executor, so the context-copying executor always
        # snapshots the user set here -- a stale value from a prior message can
        # never reach a worker. ``set`` (never ``reset``) is therefore safe.
        _WS_AUTH_USER.set(user)
        return True
    return (4401, "Unauthorized")


def _ensure_hook_registered() -> None:
    """Register the global websocket_message hook exactly once per process."""
    global _hook_registered  # noqa: PLW0603 — register the hook once per process
    with _hook_lock:
        if _hook_registered:
            return
        from dash import hooks  # noqa: PLC0415 — lazy import to avoid an import cycle

        hooks.websocket_message()(_ws_message_hook)
        _hook_registered = True


def enable_ws_auth(auth: Any, app: Any) -> None:
    """Wire WebSocket auth for a dash-auth-async app.

    No-op on backends without WebSocket support (e.g. Flask). For WS-capable
    backends it records the app->Auth mapping, installs the context-copying
    executor (before any dispatch), and registers the global hook once.

    Also ensures ``app._setup_server()`` has run so that Dash's
    ``GLOBAL_CALLBACK_MAP`` is migrated into ``app.callback_map`` before
    WebSocket callbacks are dispatched. On ASGI backends (FastAPI) the auth
    middleware short-circuits HTTP requests before the inner ``DashMiddleware``
    can run ``_setup_server`` as a before-request hook -- a WS-only client
    (no prior authenticated HTTP request) would otherwise hit an empty
    ``callback_map`` and see ``"Callback function not found"``.
    ``_setup_server`` is idempotent; calling it early is safe.
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

    # Ensure the callback map is populated before the first WS dispatch.
    setup = getattr(app, "_setup_server", None)
    if callable(setup):
        setup()

    _ensure_hook_registered()
