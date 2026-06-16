"""Unit tests for dash_auth_async.quart_client (authlib Quart integration)."""

import asyncio
import time
from types import SimpleNamespace

import pytest

pytest.importorskip("quart", reason="Quart extra dependencies are not installed")
pytest.importorskip("httpx", reason="httpx is required for the Quart OAuth client")

from dash_auth_async.quart_client import QuartIntegration


def test_state_data_roundtrip():
    integration = QuartIntegration("idp")
    session = {}

    async def run():
        await integration.set_state_data(session, "abc", {"nonce": "n"})
        assert await integration.get_state_data(session, "abc") == {"nonce": "n"}
        await integration.clear_state_data(session, "abc")
        assert await integration.get_state_data(session, "abc") is None
        assert "_state_idp_abc" not in session

    asyncio.run(run())


def test_set_state_data_sweeps_stale_keys():
    """A new login attempt must clear abandoned flows for the same provider."""
    integration = QuartIntegration("idp")
    session = {}

    async def run():
        await integration.set_state_data(session, "first", {"nonce": "n1"})
        await integration.set_state_data(session, "second", {"nonce": "n2"})
        assert "_state_idp_first" not in session
        assert "_state_idp_second" in session

    asyncio.run(run())


def test_state_data_includes_expiry_and_clear_sweeps_expired():
    integration = QuartIntegration("idp")
    session = {}

    async def run():
        await integration.set_state_data(session, "abc", {"nonce": "n"})
        assert session["_state_idp_abc"]["exp"] > time.time()

        # An expired state from another flow is swept on clear.
        session["_state_idp_x"] = {"data": {}, "exp": time.time() - 10}
        await integration.clear_state_data(session, "abc")
        assert "_state_idp_x" not in session

    asyncio.run(run())


def test_load_config_reads_app_config_with_flask_naming():
    from quart import Quart

    app = Quart(__name__)
    app.config["FOO_CLIENT_ID"] = "the-id"
    oauth = SimpleNamespace(app=app)
    config = QuartIntegration.load_config(oauth, "foo", ["client_id", "client_secret"])
    assert config == {"client_id": "the-id"}


def test_update_token_is_a_noop():
    QuartIntegration("idp").update_token({"access_token": "x"})


def _make_oauth2_app():
    from dash_auth_async.quart_client import QuartIntegration, QuartOAuth2App

    return QuartOAuth2App(
        QuartIntegration("idp"),
        name="idp",
        client_id="x",
        client_secret="y",
        authorize_url="https://idp.example/authorize",
        access_token_url="https://idp.example/token",
        client_kwargs={"scope": "openid email"},
    )


def _make_quart_app():
    from quart import Quart

    app = Quart(__name__)
    app.secret_key = "Test"
    return app


def test_authorize_redirect_saves_state_and_redirects(monkeypatch):
    from quart import session as quart_session

    app = _make_quart_app()
    client = _make_oauth2_app()

    async def fake_create_authorization_url(redirect_uri, **kwargs):
        return {
            "url": "https://idp.example/authorize?state=xyz",
            "state": "xyz",
            "nonce": "n",
        }

    monkeypatch.setattr(
        client, "create_authorization_url", fake_create_authorization_url
    )

    async def run():
        async with app.test_request_context("/oidc/idp/login", method="GET"):
            response = await client.authorize_redirect("https://app.example/cb")
            assert response.status_code == 302
            assert (
                response.headers["Location"]
                == "https://idp.example/authorize?state=xyz"
            )
            data = quart_session["_state_idp_xyz"]["data"]
            assert data["nonce"] == "n"
            assert data["redirect_uri"] == "https://app.example/cb"

    asyncio.run(run())


def test_authorize_access_token_error_param_raises():
    from authlib.integrations.base_client import OAuthError

    app = _make_quart_app()
    client = _make_oauth2_app()

    async def run():
        async with app.test_request_context(
            "/oidc/idp/callback?error=Unauthorized"
            "&error_description=something went wrong",
            method="GET",
        ):
            with pytest.raises(OAuthError) as excinfo:
                await client.authorize_access_token()
            assert "Unauthorized" in str(excinfo.value)

    asyncio.run(run())


def test_authorize_access_token_missing_state_raises():
    from authlib.integrations.base_client import OAuthError

    app = _make_quart_app()
    client = _make_oauth2_app()

    async def run():
        async with app.test_request_context(
            "/oidc/idp/callback?code=abc&state=never-saved", method="GET"
        ):
            with pytest.raises(OAuthError):
                await client.authorize_access_token()

    asyncio.run(run())


def test_oauth_init_app_stores_extension():
    from dash_auth_async.quart_client import OAuth

    app = _make_quart_app()
    oauth = OAuth(app)
    assert app.extensions["authlib.integrations.quart_client"] is oauth
    assert oauth.app is app


def test_oauth_register_populates_registry_and_creates_client():
    from dash_auth_async.quart_client import OAuth, QuartOAuth2App

    app = _make_quart_app()
    oauth = OAuth(app)
    client = oauth.register(
        "idp",
        client_id="x",
        client_secret="y",
        server_metadata_url=("https://idp.example/.well-known/openid-configuration"),
        client_kwargs={"scope": "openid email"},
    )
    assert isinstance(client, QuartOAuth2App)
    assert "idp" in oauth._registry
    assert oauth._registry["idp"][1]["client_id"] == "x"
    # create_client returns the cached instance
    assert oauth.create_client("idp") is client


def test_oauth_create_client_without_app_raises():
    from dash_auth_async.quart_client import OAuth

    oauth = OAuth()
    oauth.register("idp", client_id="x", client_kwargs={"scope": "openid"})
    assert "idp" in oauth._registry
    with pytest.raises(RuntimeError):
        oauth.create_client("idp")
