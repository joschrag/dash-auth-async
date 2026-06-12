from dash import Dash, Input, Output, dcc, html
import requests
import pytest

from dash_auth_async import basic_auth

pytest.importorskip("quart", reason="Quart extra dependencies are not installed")

TEST_USERS = {
    "valid": [["hello", "world"], ["hello2", "wo:rld"]],
    "invalid": [["hello", "password"]],
}


# Test using auth_func instead of TEST_USERS directly
def auth_function(username, password):
    if [username, password] in TEST_USERS["valid"]:
        return True
    else:
        return False


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
def test_ba002_basic_auth_login_flow(dash_br, dash_thread_server, kwargs):
    app = Dash(__name__, backend="quart", **kwargs)
    app.layout = html.Div(
        [dcc.Input(id="input", value="initial value"), html.Div(id="output")]
    )

    @app.callback(Output("output", "children"), Input("input", "value"))
    def update_output(new_value):
        return new_value

    basic_auth.BasicAuth(app, auth_func=auth_function)

    dash_thread_server(app)
    path_prefix = (
        app.config.get("url_base_pathname", "")
        or app.config.get("requests_pathname_prefix", "")
        or app.config.get("routes_pathname_prefix", "")
    )
    base_url = dash_thread_server.url + path_prefix

    def test_failed_views(url):
        assert requests.get(url).status_code == 401
        assert requests.get(url.strip("/") + "/_dash-layout").status_code == 401

    test_failed_views(base_url)

    for user, password in TEST_USERS["invalid"]:
        test_failed_views(base_url.replace("//", f"//{user}:{password}@"))

    # Test login for each user:
    for user, password in TEST_USERS["valid"]:
        # login using the URL instead of the alert popup
        # selenium has no way of accessing the alert popup
        dash_br.driver.get(base_url.replace("//", f"//{user}:{password}@"))

        # the username:password@host url doesn"t work right now for dash
        # routes, but it saves the credentials as part of the browser.
        # visiting the page again will use the saved credentials
        dash_br.driver.get(base_url)
        dash_br.wait_for_text_to_equal("#output", "initial value")


# Test incorrect initialization of BasicAuth
def both_dict_and_func(dash_br, dash_thread_server, **kwargs):
    app = Dash(__name__, backend="quart", **kwargs)
    app.layout = html.Div(
        [dcc.Input(id="input", value="initial value"), html.Div(id="output")]
    )

    basic_auth.BasicAuth(app, TEST_USERS["valid"], auth_func=auth_function)
    return True


def both_no_auth_func_or_dict(dash_br, dash_thread_server, **kwargs):
    app = Dash(__name__, backend="quart", **kwargs)
    app.layout = html.Div(
        [dcc.Input(id="input", value="initial value"), html.Div(id="output")]
    )
    basic_auth.BasicAuth(app)
    return True


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
def test_ba003_basic_auth_login_flow(dash_br, dash_thread_server, kwargs):
    with pytest.raises(ValueError):
        both_dict_and_func(dash_br, dash_thread_server, backend="quart", **kwargs)
    with pytest.raises(ValueError):
        both_no_auth_func_or_dict(
            dash_br, dash_thread_server, backend="quart", **kwargs
        )
    return
