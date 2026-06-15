"""WebSocket authentication for Dash callbacks.

Single touch-point for the Dash WebSocket internals this package depends on:
the per-app callback executor (``backend._callback_executor``) and the global
``websocket_message`` hook contract. Isolating them here keeps a future Dash
upgrade to one file.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Optional

# The authenticated user (session["user"] dict) for the callback currently being
# dispatched over a WebSocket. Set by the websocket_message hook in the WS
# context and propagated into Dash's callback worker by the context-copying
# executor. ``list_groups`` reads it when no HTTP request context is active.
_WS_AUTH_USER: "ContextVar[Optional[dict]]" = ContextVar(
    "dash_auth_async_ws_user", default=None
)
