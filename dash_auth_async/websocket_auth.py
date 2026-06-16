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
from typing import Any, Optional
from weakref import WeakKeyDictionary

# The authenticated user (session["user"] dict) for the callback currently being
# dispatched over a WebSocket. Set by the websocket_message hook in the WS
# context and propagated into Dash's callback worker by the context-copying
# executor. ``list_groups`` reads it when no HTTP request context is active.
_WS_AUTH_USER: "ContextVar[Optional[dict]]" = ContextVar(
    "dash_auth_async_ws_user", default=None
)


class _ContextCopyingExecutor(ThreadPoolExecutor):
    """A ThreadPoolExecutor that runs each task inside a copy of the context
    active at ``submit()`` time.

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
_AUTH_BY_SERVER: "WeakKeyDictionary[Any, Any]" = WeakKeyDictionary()

_hook_lock = threading.Lock()
_hook_registered = False


def _ws_message_hook(ws: Any, message: Any):
    """Global Dash websocket_message hook: authorize each callback_request.

    Returns a truthy value to allow, or a ``(code, reason)`` tuple to reject
    (which closes the socket). Resolves the owning app via ``quart.current_app``
    so it is correct when several apps share the process; inert for apps that do
    not use dash-auth-async.
    """
    if not isinstance(message, dict) or message.get("type") != "callback_request":
        return True
    try:
        import quart

        # ``quart.current_app`` is a proxy; ``_get_current_object`` unwraps it to
        # the real Quart app (the key in ``_AUTH_BY_SERVER``). The attribute is
        # present at runtime but absent from the proxy's type stub, so go through
        # ``getattr`` to keep the static type checker happy.
        current_app: Any = quart.current_app
        app = getattr(current_app, "_get_current_object")()
        auth = _AUTH_BY_SERVER.get(app)
        if auth is None:
            # Not a dash-auth-async app: nothing to enforce. Safe because the
            # registry entry is created by the developer's ``Auth(app, ...)``
            # call, not by the client -- an attacker cannot evict their own app.
            return True
        payload = message.get("payload", {}) or {}
        user = quart.session.get("user")
        if auth.authorize_ws(payload, user):
            # Load-bearing invariant: this hook runs before every callback_request
            # is submitted to the executor, so the context-copying executor always
            # snapshots the user set here -- a stale value from a prior message can
            # never reach a worker. ``set`` (never ``reset``) is therefore safe.
            _WS_AUTH_USER.set(user)
            return True
        return (4401, "Unauthorized")
    except Exception:  # pylint: disable=broad-exception-caught
        # Fail closed on any unexpected error.
        return (4401, "Unauthorized")


def _ensure_hook_registered() -> None:
    """Register the global websocket_message hook exactly once per process."""
    global _hook_registered
    with _hook_lock:
        if _hook_registered:
            return
        from dash import hooks

        hooks.websocket_message()(_ws_message_hook)
        _hook_registered = True


def enable_ws_auth(auth: Any, app: Any) -> None:
    """Wire WebSocket auth for a dash-auth-async app.

    No-op on backends without WebSocket support (e.g. Flask). For WS-capable
    backends it records the app->Auth mapping, installs the context-copying
    executor (before any dispatch), and registers the global hook once.
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
