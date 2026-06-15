"""WebSocket authentication for Dash callbacks.

Single touch-point for the Dash WebSocket internals this package depends on:
the per-app callback executor (``backend._callback_executor``) and the global
``websocket_message`` hook contract. Isolating them here keeps a future Dash
upgrade to one file.
"""

from __future__ import annotations

import contextvars
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from typing import Optional

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
