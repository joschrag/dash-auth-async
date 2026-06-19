"""End-to-end integration tests for a *protected WebSocket* callback on FastAPI.

FastAPI sibling of test_protected_callback_websocket_integration_quart.py. The
callback opts into the WebSocket transport (``websocket=True``) and streams
updates with ``set_props``; the final visible text is streamed, not returned, so
it can only arrive over the socket. The auth gate must wrap it correctly -- an
under-privileged user gets the fallback and the stream body never runs.
"""

import asyncio

import dash
import pytest
from dash import Dash, Input, Output, html, set_props

from dash_auth_async import BasicAuth, protected_callback

pytest.importorskip("fastapi", reason="FastAPI extra dependencies are not installed")

TEST_USERS = {"hello": "world", "hello2": "wo:rld"}
USER_GROUPS = {"hello": ["admin"]}


pytestmark = pytest.mark.usefixtures("reset_active_backend")


def _build_app() -> Dash:
    # websocket_callbacks=True makes the *client* open the socket; per-callback
    # websocket=True then routes this callback over it.
    app = Dash(__name__, backend="fastapi", websocket_callbacks=True)
    app.layout = html.Div(
        [
            html.Button("Start stream", id="ws-start"),
            html.Div("idle", id="ws-out"),
        ]
    )

    @protected_callback(
        Output("ws-out", "children"),
        Input("ws-start", "n_clicks"),
        groups=["admin"],
        missing_permissions_output="forbidden",
        prevent_initial_call=True,
        websocket=True,
    )
    async def stream_ws(_n_clicks):
        ws = getattr(dash.ctx, "websocket", None)
        for i in range(1, 4):
            if ws is not None and ws.is_shutdown:
                return dash.no_update
            set_props("ws-out", {"children": f"tick {i}/3"})
            await asyncio.sleep(0)
        # Final visible text is streamed, not returned: proves the WebSocket push.
        set_props("ws-out", {"children": "streamed"})
        return dash.no_update

    return app


def _login(dash_br, base_url, username, password):
    dash_br.driver.get(base_url.replace("//", f"//{username}:{password}@"))
    dash_br.driver.get(base_url)


def test_pcwf001_authorized_protected_websocket_callback_streams_set_props(
    dash_br, dash_thread_server
):
    """An authorised user sees the value pushed via ``set_props`` over the socket."""
    app = _build_app()
    BasicAuth(app, TEST_USERS, user_groups=USER_GROUPS, secret_key="Test!")

    dash_thread_server(app)
    base_url = dash_thread_server.url
    _login(dash_br, base_url, "hello", "world")

    dash_br.wait_for_text_to_equal("#ws-out", "idle")
    dash_br.find_element("#ws-start").click()
    dash_br.wait_for_text_to_equal("#ws-out", "streamed")


def test_pcwf002_missing_permissions_protected_websocket_callback_emits_fallback(
    dash_br, dash_thread_server
):
    """An authenticated user without the group gets the fallback, never the stream."""
    app = _build_app()
    BasicAuth(app, TEST_USERS, user_groups=USER_GROUPS, secret_key="Test!")

    dash_thread_server(app)
    base_url = dash_thread_server.url
    # "hello2" authenticates but has no groups -> admin gate rejects it.
    _login(dash_br, base_url, "hello2", "wo:rld")

    dash_br.wait_for_text_to_equal("#ws-out", "idle")
    dash_br.find_element("#ws-start").click()
    dash_br.wait_for_text_to_equal("#ws-out", "forbidden")
