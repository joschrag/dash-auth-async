from unittest.mock import patch

import pytest
import requests
from dash import Dash, Input, Output, dcc, html

from dash_auth_async import OIDCAuth, protected_callback

pytest.importorskip("fastapi", reason="FastAPI extra dependencies are not installed")

from starlette.responses import RedirectResponse

_OAUTH_APP = "authlib.integrations.starlette_client.apps.StarletteOAuth2App"
_METADATA_URL = "https://idp2.com/oidc/2/.well-known/openid-configuration"


pytestmark = pytest.mark.usefixtures("reset_active_backend")


async def valid_authorize_redirect(self, request, redirect_uri, *args, **kwargs):
    return RedirectResponse("/" + redirect_uri.split("/", maxsplit=3)[-1])


async def invalid_authorize_redirect(self, request, redirect_uri, *args, **kwargs):
    base_url = "/" + redirect_uri.split("/", maxsplit=3)[-1]
    return RedirectResponse(
        f"{base_url}?error=Unauthorized&error_description=something went wrong"
    )


async def valid_authorize_access_token(self, request, *args, **kwargs):
    return {
        "userinfo": {"email": "a.b@mail.com", "groups": ["viewer", "editor"]},
        "refresh_token": "ABCDEF",
    }


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
@patch(f"{_OAUTH_APP}.authorize_redirect", valid_authorize_redirect)
@patch(f"{_OAUTH_APP}.authorize_access_token", valid_authorize_access_token)
def test_oaf001_oidc_auth_login_flow_success(dash_br, dash_thread_server, kwargs):
    app = Dash(__name__, backend="fastapi", **kwargs)
    app.layout = html.Div(
        [
            dcc.Input(id="input", value="initial value"),
            html.Div(id="output1"),
            html.Div(id="output2"),
            html.Div("static", id="output3"),
            html.Div("static", id="output4"),
            html.Div("not static", id="output5"),
        ]
    )

    @app.callback(Output("output1", "children"), Input("input", "value"))
    def update_output1(new_value):
        return new_value

    @protected_callback(
        Output("output2", "children"),
        Input("input", "value"),
        groups=["editor"],
        check_type="one_of",
    )
    def update_output2(new_value):
        return new_value

    @protected_callback(
        Output("output3", "children"),
        Input("input", "value"),
        groups=["admin"],
        check_type="one_of",
    )
    def update_output3(new_value):
        return new_value

    @protected_callback(
        Output("output4", "children"),
        Input("input", "value"),
        groups=["viewer"],
        check_type="none_of",
    )
    def update_output4(new_value):
        return new_value

    @protected_callback(
        Output("output5", "children"),
        Input("input", "value"),
        groups=["viewer", "editor"],
        check_type="all_of",
    )
    def update_output5(new_value):
        return new_value

    oidc = OIDCAuth(app, secret_key="Test")
    oidc.register_provider(
        "oidc",
        token_endpoint_auth_method="client_secret_post",
        client_id="<client-id>",
        client_secret="<client-secret>",
        server_metadata_url=_METADATA_URL,
    )
    dash_thread_server(app)
    path_prefix = (
        app.config.get("url_base_pathname", "")
        or app.config.get("requests_pathname_prefix", "")
        or app.config.get("routes_pathname_prefix", "")
    )
    base_url = dash_thread_server.url + path_prefix

    assert requests.get(base_url).status_code == 200

    dash_br.driver.get(base_url)
    dash_br.wait_for_text_to_equal("#output1", "initial value")
    dash_br.wait_for_text_to_equal("#output2", "initial value")
    dash_br.wait_for_text_to_equal("#output3", "static")
    dash_br.wait_for_text_to_equal("#output4", "static")
    dash_br.wait_for_text_to_equal("#output5", "initial value")


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
@patch(f"{_OAUTH_APP}.authorize_redirect", invalid_authorize_redirect)
def test_oaf002_oidc_auth_login_fail(dash_thread_server, kwargs):
    app = Dash(__name__, backend="fastapi", **kwargs)
    app.layout = html.Div(
        [dcc.Input(id="input", value="initial value"), html.Div(id="output")]
    )

    @app.callback(Output("output", "children"), Input("input", "value"))
    def update_output(new_value):
        return new_value

    oidc = OIDCAuth(app, public_routes=["/public"], secret_key="Test")
    oidc.register_provider(
        "oidc",
        token_endpoint_auth_method="client_secret_post",
        client_id="<client-id>",
        client_secret="<client-secret>",
        server_metadata_url=_METADATA_URL,
    )
    dash_thread_server(app)
    path_prefix = (
        app.config.get("url_base_pathname", "")
        or app.config.get("requests_pathname_prefix", "")
        or app.config.get("routes_pathname_prefix", "")
    )
    base_url = dash_thread_server.url + path_prefix

    def test_unauthorized(url):
        r = requests.get(url)
        assert r.status_code == 401
        assert r.text == "Unauthorized: something went wrong"

    def test_authorized(url):
        assert requests.get(url).status_code == 200

    test_unauthorized(base_url)
    test_authorized(base_url.rstrip("/") + "/public")


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
@patch(f"{_OAUTH_APP}.authorize_redirect", valid_authorize_redirect)
@patch(f"{_OAUTH_APP}.authorize_access_token", valid_authorize_access_token)
def test_oaf003_oidc_auth_login_several_idp(dash_br, dash_thread_server, kwargs):
    app = Dash(__name__, backend="fastapi", **kwargs)
    app.layout = html.Div(
        [
            dcc.Input(id="input", value="initial value"),
            html.Div(id="output1"),
        ]
    )

    @app.callback(Output("output1", "children"), Input("input", "value"))
    def update_output1(new_value):
        return new_value

    oidc = OIDCAuth(app, secret_key="Test")
    oidc.register_provider(
        "idp1",
        token_endpoint_auth_method="client_secret_post",
        client_id="<client-id>",
        client_secret="<client-secret>",
        server_metadata_url=_METADATA_URL,
    )
    oidc.register_provider(
        "idp2",
        token_endpoint_auth_method="client_secret_post",
        client_id="<client-id2>",
        client_secret="<client-secret2>",
        server_metadata_url=_METADATA_URL,
    )

    dash_thread_server(app)
    path_prefix = (
        app.config.get("url_base_pathname", "")
        or app.config.get("requests_pathname_prefix", "")
        or app.config.get("routes_pathname_prefix", "")
    )
    base_url = dash_thread_server.url
    base_url_prefix = (base_url + path_prefix).rstrip("/")
    assert requests.get(base_url).status_code == 400
    assert requests.get(base_url_prefix).status_code == 400

    assert requests.get(base_url + "/oidc/idp1/login").status_code == 200
    assert requests.get(base_url + "/oidc/logout").status_code == 200
    assert requests.get(base_url).status_code == 400
    assert requests.get(base_url + "/oidc/idp2/login").status_code == 200

    dash_br.driver.get(base_url + "/oidc/idp2/login")
    dash_br.driver.get(base_url_prefix)
    dash_br.wait_for_text_to_equal("#output1", "initial value")
