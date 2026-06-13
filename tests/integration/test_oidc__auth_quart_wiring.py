"""OIDCAuth construction/wiring on a Quart-backed Dash app (no browser)."""

import asyncio

import pytest
from dash import Dash

from dash_auth_async import OIDCAuth
from dash_auth_async.oidc_auth import get_oauth

pytest.importorskip("quart", reason="Quart extra dependencies are not installed")
pytest.importorskip("httpx", reason="httpx is required for the Quart OAuth client")

_METADATA_URL = "https://idp2.com/oidc/2/.well-known/openid-configuration"


def _make_oidc_app():
    app = Dash(__name__, backend="quart")
    oidc = OIDCAuth(app, secret_key="Test")
    oidc.register_provider(
        "idp",
        token_endpoint_auth_method="client_secret_post",
        client_id="<client-id>",
        client_secret="<client-secret>",
        server_metadata_url=_METADATA_URL,
    )
    return app, oidc


def test_quart_backend_uses_quart_oauth_registry():
    from dash_auth_async import quart_client

    app, oidc = _make_oidc_app()
    assert isinstance(oidc.oauth, quart_client.OAuth)
    assert app.server.extensions["authlib.integrations.quart_client"] is oidc.oauth
    assert isinstance(oidc.get_oauth_client("idp"), quart_client.QuartOAuth2App)


def test_oidc_routes_registered_with_same_endpoints():
    app, _ = _make_oidc_app()
    endpoints = {rule.endpoint for rule in app.server.url_map.iter_rules()}
    assert {"oidc_login", "oidc_logout", "oidc_callback"} <= endpoints


def test_get_oauth_finds_quart_extension():
    app, oidc = _make_oidc_app()
    assert get_oauth(app) is oidc.oauth


def test_login_request_returns_awaitable_on_quart():
    import inspect

    app, oidc = _make_oidc_app()

    async def run():
        async with app.server.test_request_context("/", method="GET"):
            result = oidc.login_request("unknown-idp-name")
            assert inspect.isawaitable(result)
            # unknown idp with a single provider falls back to that provider;
            # awaiting would hit the network (metadata fetch), so just close.
            result.close()

    asyncio.run(run())


def test_callback_unknown_idp_returns_400():
    app, oidc = _make_oidc_app()

    async def run():
        async with app.server.test_request_context("/oidc/nope/callback", method="GET"):
            body, status = await oidc._callback_async("nope")
            assert status == 400
            assert "not a valid registered idp" in body

    asyncio.run(run())
