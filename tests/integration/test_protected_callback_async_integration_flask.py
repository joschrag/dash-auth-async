"""End-to-end integration tests for an async ``protected_callback`` on the
*default Flask backend*.

The Flask backend has no WebSocket transport; instead, with ``dash[async]``
installed (asgiref), Dash dispatches ``async def`` callbacks over HTTP via an
async view (``backends/_flask.py`` ``_dispatch_async`` awaits the coroutine).
This proves ``protected_callback`` keeps the coroutine intact on the Flask
async-over-HTTP path too -- not just the Quart/WebSocket path.

See https://dash.plotly.com/advanced-callbacks#using-async/await-in-callbacks
(``pip install "dash[async]"`` enables Flask async).
"""

import asyncio

from dash import Dash, Input, Output, dcc, html
import pytest

from dash_auth_async import BasicAuth, protected_callback

pytest.importorskip(
    "asgiref",
    reason="dash[async] (asgiref) is required for async callbacks on the Flask backend",
)

TEST_USERS = {"hello": "world", "hello2": "wo:rld"}
USER_GROUPS = {"hello": ["admin"]}


def _build_app() -> Dash:
    # No backend= kwarg: this is the default Flask backend. With asgiref present,
    # Dash auto-enables use_async and serves async callbacks over HTTP.
    app = Dash(__name__)
    assert app._use_async, "async support should be auto-enabled on Flask via asgiref"

    app.layout = html.Div(
        [
            dcc.Input(id="input", value="initial value"),
            html.Div(id="async-out"),
        ]
    )

    @protected_callback(
        Output("async-out", "children"),
        Input("input", "value"),
        groups=["admin"],
        missing_permissions_output="forbidden",
        unauthenticated_output="unauthenticated",
    )
    async def update_async_out(new_value):
        # Yield to the event loop so the value only appears if the coroutine was
        # actually awaited on the Flask async view, not merely instantiated.
        await asyncio.sleep(0)
        return f"async:{new_value}"

    return app


def test_pcf001_authorized_async_protected_callback_on_flask_returns_awaited_output(
    dash_br, dash_thread_server
):
    """An authorised user receives the awaited output over Flask's async HTTP view."""
    app = _build_app()
    BasicAuth(app, TEST_USERS, user_groups=USER_GROUPS, secret_key="Test!")

    dash_thread_server(app)
    base_url = dash_thread_server.url
    dash_br.driver.get(base_url.replace("//", "//hello:world@"))
    dash_br.driver.get(base_url)

    dash_br.wait_for_text_to_equal("#async-out", "async:initial value")


def test_pcf002_missing_permissions_async_protected_callback_on_flask_emits_fallback(
    dash_br, dash_thread_server
):
    """An authenticated user without the group gets ``missing_permissions_output``."""
    app = _build_app()
    BasicAuth(app, TEST_USERS, user_groups=USER_GROUPS, secret_key="Test!")

    dash_thread_server(app)
    base_url = dash_thread_server.url
    dash_br.driver.get(base_url.replace("//", "//hello2:wo:rld@"))
    dash_br.driver.get(base_url)

    dash_br.wait_for_text_to_equal("#async-out", "forbidden")
