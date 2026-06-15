"""Private page: a simulated long-running task streamed over the WebSocket.

This page is NOT in public_routes, so loading it requires BasicAuth login. The
callback is a plain @callback: the page is only reachable when authenticated and
no user-group gating is required. Streaming follows the same async + set_props +
is_shutdown pattern as the public page.
"""

import asyncio

import dash
from dash import Input, Output, callback, ctx, html, register_page, set_props

register_page(__name__, path="/private", name="Private")

layout = html.Div(
    [
        html.H1("Simulated task (private)"),
        html.P("You are logged in — this page sits behind BasicAuth."),
        html.Button("Run task", id="task-start"),
        html.Div(
            html.Progress(id="task-bar", value="0", max="100"),
            style={"marginTop": "1rem"},
        ),
        html.Div("Idle.", id="task-status", style={"marginTop": "1rem"}),
    ],
    style={"padding": "1rem"},
)


@callback(
    Output("task-status", "children"),
    Input("task-start", "n_clicks"),
    prevent_initial_call=True,
)
async def run_task(_n_clicks):
    ws = getattr(ctx, "websocket", None)
    for pct in range(0, 101, 10):
        if ws is not None and ws.is_shutdown:
            return dash.no_update
        set_props("task-bar", {"value": str(pct)})
        set_props("task-status", {"children": f"Working… {pct}%"})
        await asyncio.sleep(0.5)
    set_props("task-bar", {"value": "100"})
    return "Complete!"
