import pytest
import requests
from dash import Dash, Input, Output, dcc, html

from dash_auth_async import BasicAuth, add_public_routes, protected

pytest.importorskip("fastapi", reason="FastAPI extra dependencies are not installed")

TEST_USERS = {
    "valid": [["hello", "world"], ["hello2", "wo:rld"]],
    "invalid": [["hello", "password"]],
}


pytestmark = pytest.mark.usefixtures("reset_active_backend")


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"url_base_pathname": "/app/"},
        {"url_base_pathname": "/sub/app/"},
        {
            "routes_pathname_prefix": "/app/",
            "requests_pathname_prefix": "/app/",
        },
    ],
)
def test_ba001_basic_auth_login_flow(dash_br, dash_thread_server, kwargs):
    app = Dash(__name__, backend="fastapi", **kwargs)
    app.layout = html.Div(
        [dcc.Input(id="input", value="initial value"), html.Div(id="output")]
    )

    @app.callback(Output("output", "children"), Input("input", "value"))
    def update_output(new_value):
        return new_value

    BasicAuth(app, TEST_USERS["valid"], public_routes=["/home"])
    add_public_routes(app, ["/user/<user_id>/public"])

    dash_thread_server(app)
    path_prefix = (
        app.config.get("url_base_pathname", "")
        or app.config.get("requests_pathname_prefix", "")
        or app.config.get("routes_pathname_prefix", "")
    )
    base_url = dash_thread_server.url + path_prefix

    def test_failed_views(url):
        assert requests.get(url).status_code == 401

    def test_successful_views(url):
        assert requests.get(url.rstrip("/") + "/_dash-layout").status_code == 200
        assert requests.get(url.rstrip("/") + "/home").status_code == 200
        assert requests.get(url.rstrip("/") + "/user/john123/public").status_code == 200

    test_failed_views(base_url)
    test_successful_views(base_url)

    for user, password in TEST_USERS["invalid"]:
        test_failed_views(base_url.replace("//", f"//{user}:{password}@"))
        test_successful_views(base_url.replace("//", f"//{user}:{password}@"))

    for user, password in TEST_USERS["valid"]:
        dash_br.driver.get(base_url.replace("//", f"//{user}:{password}@"))
        dash_br.driver.get(base_url)
        dash_br.wait_for_text_to_equal("#output", "initial value")


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"url_base_pathname": "/app/"},
        {"url_base_pathname": "/sub/app/"},
        {
            "routes_pathname_prefix": "/app/",
            "requests_pathname_prefix": "/app/",
        },
    ],
)
def test_ba002_basic_auth_groups(dash_br, dash_thread_server, kwargs):
    app = Dash(__name__, backend="fastapi", **kwargs)
    app.layout = html.Div(
        [dcc.Input(id="input", value="initial value"), html.Div(id="output")]
    )

    @app.callback(
        Output("output", "children"),
        Input("input", "value"),
        groups=["admin"],
    )
    @protected(
        unauthenticated_output="unauthenticated",
        missing_permissions_output="forbidden",
        groups=["admin"],
    )
    def update_output(new_value):
        return new_value

    BasicAuth(
        app,
        TEST_USERS["valid"],
        public_routes=["/home"],
        user_groups={"hello": ["admin"]},
        secret_key="Test!",
    )

    dash_thread_server(app)
    path_prefix = (
        app.config.get("url_base_pathname", "")
        or app.config.get("requests_pathname_prefix", "")
        or app.config.get("routes_pathname_prefix", "")
    )
    base_url = dash_thread_server.url + path_prefix

    for user, password in TEST_USERS["valid"]:
        dash_br.driver.get(base_url.replace("//", f"//{user}:{password}@"))
        dash_br.driver.get(base_url)
        expected = "initial value" if user == "hello" else "forbidden"
        dash_br.wait_for_text_to_equal("#output", expected)
