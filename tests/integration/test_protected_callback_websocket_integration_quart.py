"""End-to-end integration tests for a *protected WebSocket* callback.

Unlike the async-over-HTTP tests, these opt the callback into the WebSocket
transport (``websocket=True``) and stream updates with ``set_props`` -- the
canonical streaming pattern from https://dash.plotly.com/websocket-callbacks
(``async def`` + ``set_props`` + ``ctx.websocket.is_shutdown``). WebSocket
callbacks require a Quart/FastAPI backend.

The streamed text is pushed via ``set_props`` while the callback *returns*
``dash.no_update``: the value that lands in ``#ws-out`` can therefore only have
arrived over the WebSocket push, which isolates the streaming mechanism from a
plain async return value. The auth gate must still wrap this correctly -- an
unauthorised user gets the fallback and the stream body never runs.
"""

import asyncio

import dash
import pytest
from dash import Dash, Input, Output, html, set_props

from dash_auth_async import BasicAuth, protected_callback

pytest.importorskip("quart", reason="Quart extra dependencies are not installed")

TEST_USERS = {"hello": "world", "hello2": "wo:rld"}
USER_GROUPS = {"hello": ["admin"]}


def _build_app() -> Dash:
    # websocket_callbacks=True makes the *client* open the socket; per-callback
    # websocket=True then routes this callback over it. Without the constructor
    # flag the config ships ``websocket.enabled=False`` and the browser never
    # connects, so the callback would silently never fire.
    app = Dash(__name__, backend="quart", websocket_callbacks=True)
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
            # Push intermediate frames over the socket.
            set_props("ws-out", {"children": f"tick {i}/3"})
            await asyncio.sleep(0)
        # Final visible text is streamed, not returned: proves the WebSocket push.
        set_props("ws-out", {"children": "streamed"})
        return dash.no_update

    return app


def _login_admin(dash_br, base_url):
    dash_br.driver.get(base_url.replace("//", "//hello:world@"))
    dash_br.driver.get(base_url)


def test_pcw001_authorized_protected_websocket_callback_streams_set_props(
    dash_br, dash_thread_server
):
    """An authorised user sees the value pushed via ``set_props`` over the socket.

    The callback returns ``dash.no_update``; only a working WebSocket stream can
    make ``#ws-out`` read ``streamed``.
    """
    app = _build_app()
    BasicAuth(app, TEST_USERS, user_groups=USER_GROUPS, secret_key="Test!")

    dash_thread_server(app)
    base_url = dash_thread_server.url
    _login_admin(dash_br, base_url)

    dash_br.wait_for_text_to_equal("#ws-out", "idle")
    dash_br.find_element("#ws-start").click()
    dash_br.wait_for_text_to_equal("#ws-out", "streamed")


def test_pcw002_missing_permissions_protected_websocket_callback_emits_fallback(
    dash_br, dash_thread_server
):
    """An authenticated user without the group gets the fallback, never the stream.

    The gate short-circuits before the coroutine body, so no ``set_props`` frame
    is ever pushed and ``#ws-out`` shows ``forbidden``.
    """
    app = _build_app()
    BasicAuth(app, TEST_USERS, user_groups=USER_GROUPS, secret_key="Test!")

    dash_thread_server(app)
    base_url = dash_thread_server.url
    # "hello2" authenticates but has no groups -> admin gate rejects it.
    dash_br.driver.get(base_url.replace("//", "//hello2:wo:rld@"))
    dash_br.driver.get(base_url)

    dash_br.wait_for_text_to_equal("#ws-out", "idle")
    dash_br.find_element("#ws-start").click()
    dash_br.wait_for_text_to_equal("#ws-out", "forbidden")
