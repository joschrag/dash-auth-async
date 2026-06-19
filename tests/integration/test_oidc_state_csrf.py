"""OIDC OAuth state/CSRF validation, driven through real authlib (no mock IDP).

The browser OIDC tests patch ``authorize_redirect``/``authorize_access_token``,
so authlib's anti-CSRF state check never actually runs there. These tests drive
the *real* authlib state path on a Flask backend via its test client to lock the
invariant against future authlib changes: ``/login`` stores the generated state
in the session, and ``/callback`` presented with a tampered or missing state must
be rejected with 401 (the ``except OAuthError`` branch in ``OIDCAuth.callback``),
never silently accepted.

authlib validates state before any token-endpoint call, so registering the
provider with explicit endpoints keeps the whole flow offline.
"""

from urllib.parse import parse_qs, urlparse

import pytest
from dash import Dash, html

from dash_auth_async import OIDCAuth

_AUTHORIZE_URL = "https://idp.example/authorize"
_TOKEN_URL = "https://idp.example/token"


pytestmark = pytest.mark.usefixtures("reset_active_backend")


def _make_client():
    app = Dash(__name__)
    app.layout = html.Div("state-csrf")  # Dash validates layout on first request
    oidc = OIDCAuth(app, secret_key="state-csrf-secret")
    oidc.register_provider(
        "idp",
        client_id="client-id",
        client_secret="client-secret",
        authorize_url=_AUTHORIZE_URL,
        access_token_url=_TOKEN_URL,
    )
    # The Flask test client persists the session cookie across requests, so the
    # state stored at /login is presented back at /callback automatically.
    return app.server.test_client()


def _login_and_capture_state(client) -> str:
    resp = client.get("/oidc/idp/login")
    assert resp.status_code == 302
    query = parse_qs(urlparse(resp.headers["Location"]).query)
    # authlib generated a state and stored it in the session before redirecting.
    assert "state" in query
    return query["state"][0]


def test_oidc_callback_rejects_tampered_state():
    client = _make_client()
    real_state = _login_and_capture_state(client)

    resp = client.get(f"/oidc/idp/callback?code=fake-code&state={real_state}-tampered")
    assert resp.status_code == 401


def test_oidc_callback_rejects_missing_state():
    client = _make_client()
    _login_and_capture_state(client)

    resp = client.get("/oidc/idp/callback?code=fake-code")
    assert resp.status_code == 401
