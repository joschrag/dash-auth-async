"""OIDCAuth construction/wiring on a FastAPI-backed Dash app (no browser)."""

import asyncio

import pytest
from dash import Dash, dcc, html

from dash_auth_async import OIDCAuth
from dash_auth_async.oidc_auth import get_oauth

pytest.importorskip("fastapi", reason="FastAPI extra dependencies are not installed")

_METADATA_URL = "https://idp2.com/oidc/2/.well-known/openid-configuration"


def _make_oidc_app():
    app = Dash(__name__, backend="fastapi")
    app.layout = html.Div(
        [dcc.Input(id="input", value="initial value"), html.Div(id="output")]
    )
    oidc = OIDCAuth(app, secret_key="Test")
    oidc.register_provider(
        "idp",
        token_endpoint_auth_method="client_secret_post",
        client_id="<client-id>",
        client_secret="<client-secret>",
        server_metadata_url=_METADATA_URL,
    )
    return app, oidc


def test_fastapi_backend_uses_starlette_oauth_registry():
    from authlib.integrations.starlette_client import (
        OAuth as StarletteOAuth,
        StarletteOAuth2App,
    )

    app, oidc = _make_oidc_app()
    assert isinstance(oidc.oauth, StarletteOAuth)
    assert app.server.state.dash_auth_oauth is oidc.oauth
    assert isinstance(oidc.get_oauth_client("idp"), StarletteOAuth2App)


def test_oidc_routes_registered_with_translated_idp_placeholder():
    app, _ = _make_oidc_app()
    paths = {route.path for route in app.server.routes if hasattr(route, "path")}
    assert "/oidc/{idp}/login" in paths
    assert "/oidc/{idp}/callback" in paths
    assert "/oidc/logout" in paths
    names = {route.name for route in app.server.routes if hasattr(route, "name")}
    assert {"oidc_login", "oidc_logout", "oidc_callback"} <= names


def test_get_oauth_finds_state_registry():
    app, oidc = _make_oidc_app()
    assert get_oauth(app) is oidc.oauth


def test_callback_unknown_idp_returns_400():
    from starlette.requests import Request

    from dash_auth_async.backends import _current_request_var

    _, oidc = _make_oidc_app()
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/oidc/nope/callback",
        "headers": [],
        "query_string": b"",
    }
    request = Request(scope)

    async def run():
        # The merged async callback resolves the request from the ContextVar
        # (set by the auth middleware in a live request) rather than a param.
        token = _current_request_var.set(request)
        try:
            response = await oidc._callback_async("nope")
        finally:
            _current_request_var.reset(token)
        assert response.status_code == 400
        assert b"not a valid registered idp" in response.body

    asyncio.run(run())
