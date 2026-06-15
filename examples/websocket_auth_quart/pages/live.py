"""Public page: a live counter/clock streamed over the WebSocket.

Uses public_callback so the callback is whitelisted by dash-auth-async even if a
leg is served over HTTP. When routed over the WebSocket the whitelist is simply
unused. The streaming pattern (async + set_props + is_shutdown) follows
https://dash.plotly.com/websocket-callbacks.
"""

import asyncio
from datetime import datetime

import dash
from dash import Input, Output, ctx, html, register_page, set_props

from dash_auth_async import public_callback

register_page(__name__, path="/live", name="Live")

layout = html.Div(
    [
        html.H1("Live counter / clock (public)"),
        html.P("Anyone can view this page and start the stream — no login required."),
        html.Button("Start stream", id="counter-start"),
        html.Div(
            "Press start.",
            id="counter-out",
            style={"marginTop": "1rem", "fontSize": "1.5rem"},
        ),
    ],
    style={"padding": "1rem"},
)


@public_callback(
    Output("counter-out", "children"),
    Input("counter-start", "n_clicks"),
    prevent_initial_call=True,
)
async def stream_counter(_n_clicks):
    ws = getattr(ctx, "websocket", None)
    for i in range(1, 11):
        if ws is not None and ws.is_shutdown:
            return dash.no_update
        set_props(
            "counter-out",
            {"children": f"Tick {i}/10 — {datetime.now():%H:%M:%S}"},
        )
        await asyncio.sleep(1)
    return "Done."
