"""End-to-end integration tests for async ``protected_callback`` callbacks.

These drive a live Quart-backed Dash app over its real WebSocket transport
(via a browser), which is the only place the async regression surfaces:
Dash chooses sync-vs-async dispatch *once at registration* from
``asyncio.iscoroutinefunction`` (dash ``_callback.py``), and the Quart
WebSocket runner only ``asyncio.run``s a callback result when it is a
coroutine (dash ``backends/ws.py``). If ``protected_callback`` were to hand
Dash a plain ``def`` wrapper, the coroutine would be *created but never
awaited*: ``set_props``/the return value never reach the DOM and
``wait_for_text_to_equal`` below would time out.

The corresponding registration-level checks live in
``tests/unit/test_protected_callback_async.py``; here we prove the awaited
value actually streams back across the socket.
"""

import asyncio

import pytest
from dash import Dash, Input, Output, dcc, html

from dash_auth_async import BasicAuth, protected_callback

pytest.importorskip("quart", reason="Quart extra dependencies are not installed")

# "hello" is granted the admin group; "hello2" is authenticated but group-less,
# so the same admin-gated callback authorises one and rejects the other.
TEST_USERS = {"hello": "world", "hello2": "wo:rld"}
USER_GROUPS = {"hello": ["admin"]}


pytestmark = pytest.mark.usefixtures("reset_active_backend")


def _path_prefix(app: Dash) -> str:
    return (
        app.config.get("url_base_pathname", "")
        or app.config.get("requests_pathname_prefix", "")
        or app.config.get("routes_pathname_prefix", "")
    )


def _build_app(**kwargs) -> Dash:
    """A Quart Dash app whose admin-gated callback is a real coroutine."""
    app = Dash(__name__, backend="quart", **kwargs)
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
        # Yield to the event loop so a value can only appear if the coroutine
        # was genuinely awaited, not merely instantiated.
        await asyncio.sleep(0)
        return f"async:{new_value}"

    return app


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"url_base_pathname": "/app/"},
    ],
)
def test_pca001_authorized_async_protected_callback_streams_awaited_output(
    dash_br, dash_thread_server, kwargs
):
    """An authorised user receives the *awaited* output of an async callback.

    This is the core regression: pre-fix the coroutine was registered on the
    sync path, created but never awaited, so ``#async-out`` never updated.
    """
    app = _build_app(**kwargs)
    BasicAuth(
        app,
        TEST_USERS,
        user_groups=USER_GROUPS,
        secret_key="Test!",
    )

    dash_thread_server(app)
    base_url = dash_thread_server.url + _path_prefix(app)

    # Seed saved credentials for the admin user, then load the app plainly.
    dash_br.driver.get(base_url.replace("//", "//hello:world@"))
    dash_br.driver.get(base_url)

    dash_br.wait_for_text_to_equal("#async-out", "async:initial value")


def test_pca002_missing_permissions_async_protected_callback_emits_fallback(
    dash_br, dash_thread_server
):
    """An authenticated user without the group gets ``missing_permissions_output``.

    Confirms the auth gate still short-circuits *before* the coroutine body on
    the async dispatch path (the fallback is returned, the await never runs).
    """
    app = _build_app()
    BasicAuth(
        app,
        TEST_USERS,
        user_groups=USER_GROUPS,
        secret_key="Test!",
    )

    dash_thread_server(app)
    base_url = dash_thread_server.url + _path_prefix(app)

    # "hello2" authenticates but holds no groups -> admin gate rejects it.
    dash_br.driver.get(base_url.replace("//", "//hello2:wo:rld@"))
    dash_br.driver.get(base_url)

    dash_br.wait_for_text_to_equal("#async-out", "forbidden")
