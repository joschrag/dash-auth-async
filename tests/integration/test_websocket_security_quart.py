"""Security: the websocket callback endpoint must not bypass authentication.

Drives the raw socket with websocket-client (no browser) and asserts an
unauthenticated client cannot invoke a private callback, while a public_callback
still streams unauthenticated.
"""

import json

import pytest
import websocket  # websocket-client (synchronous)
from dash import Dash, Input, Output, callback, html

from dash_auth_async import BasicAuth, public_callback

pytest.importorskip("quart", reason="Quart extra dependencies are not installed")


def _build_app() -> Dash:
    app = Dash(__name__, backend="quart", websocket_callbacks=True)
    app.layout = html.Div(
        [
            html.Button("p", id="priv-in"),
            html.Div("idle", id="priv-out"),
            html.Button("u", id="pub-in"),
            html.Div("idle", id="pub-out"),
        ]
    )

    @callback(
        Output("priv-out", "children"),
        Input("priv-in", "n_clicks"),
        prevent_initial_call=True,
        websocket=True,
    )
    def private(_n):
        return "TOP-SECRET-USER-DATA"

    @public_callback(
        Output("pub-out", "children"),
        Input("pub-in", "n_clicks"),
        prevent_initial_call=True,
        websocket=True,
    )
    async def public(_n):
        return "PUBLIC-OK"

    BasicAuth(app, {"hello": "world"}, secret_key="Test!")
    return app


def _send_callback_request(ws_url, origin, output, comp_id, in_id):
    conn = websocket.create_connection(ws_url, header=[f"Origin: {origin}"], timeout=8)
    try:
        conn.send(
            json.dumps(
                {
                    "type": "callback_request",
                    "requestId": "1",
                    "rendererId": "r1",
                    "payload": {
                        "output": output,
                        "outputs": {"id": comp_id, "property": "children"},
                        "inputs": [{"id": in_id, "property": "n_clicks", "value": 1}],
                        "changedPropIds": [f"{in_id}.n_clicks"],
                        "state": [],
                    },
                }
            )
        )
        frames = []
        for _ in range(5):
            try:
                frames.append(str(conn.recv()))
            except Exception:
                break
        return "".join(frames)
    finally:
        try:
            conn.close()
        except Exception:
            pass


def test_unauthenticated_ws_cannot_invoke_private_callback(dash_thread_server):
    app = _build_app()
    dash_thread_server(app)
    base = dash_thread_server.url
    ws_url = base.replace("http://", "ws://") + "/_dash-ws-callback"

    received = _send_callback_request(
        ws_url, base, "priv-out.children", "priv-out", "priv-in"
    )
    assert "TOP-SECRET-USER-DATA" not in received


def test_unauthenticated_ws_can_invoke_public_callback(dash_thread_server):
    app = _build_app()
    dash_thread_server(app)
    base = dash_thread_server.url
    ws_url = base.replace("http://", "ws://") + "/_dash-ws-callback"

    received = _send_callback_request(
        ws_url, base, "pub-out.children", "pub-out", "pub-in"
    )
    assert "PUBLIC-OK" in received
