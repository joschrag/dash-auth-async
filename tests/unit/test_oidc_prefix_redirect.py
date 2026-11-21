"""Browser-facing OIDC redirects honour requests_pathname_prefix.

Under a mount or proxy prefix Dash is configured with
``requests_pathname_prefix="/app/"`` while ``routes_pathname_prefix`` stays
``"/"``. The post-login redirect and the logout page's "Go back" link used the
routes prefix, sending users to the site root, outside the app.
"""

import pytest
from dash import Dash, html

pytest.importorskip("authlib", reason="OIDC extra dependencies are not installed")

from dash_auth_async import OIDCAuth

pytestmark = pytest.mark.usefixtures("reset_active_backend")


@pytest.mark.parametrize(
    ("dash_kwargs", "expected"),
    [
        ({"requests_pathname_prefix": "/app/", "routes_pathname_prefix": "/"}, "/app/"),
        ({"url_base_pathname": "/app/"}, "/app/"),
        ({}, "/"),
    ],
)
def test_login_and_logout_point_at_the_browser_prefix(dash_kwargs, expected):
    app = Dash(__name__, **dash_kwargs)
    app.layout = html.Div("x")
    auth = OIDCAuth(app, secret_key="Test")
    auth.register_provider(
        "idp",
        client_id="c",
        client_secret="s",
        server_metadata_url="https://idp.example/.well-known/openid-configuration",
    )
    with app.server.test_request_context("/"):
        response = auth.after_logged_in({"email": "a@b.c"}, "idp", {})
        assert response.headers["Location"] == expected
        assert f'<a href="{expected}">Go back</a>' in auth.logout()
