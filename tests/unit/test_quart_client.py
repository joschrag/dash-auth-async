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


# --------------------------------------------------------------------------- #
# Successful token exchange: the stored nonce must reach id_token validation
# --------------------------------------------------------------------------- #
ISSUER = "https://idp.example"


def _signed_id_token_client():
    """A client whose IdP metadata carries an in-memory JWKS, plus a signer."""
    from joserfc import jwt
    from joserfc.jwk import KeySet, RSAKey

    from dash_auth_async.quart_client import QuartIntegration, QuartOAuth2App

    key = RSAKey.generate_key(2048, parameters={"kid": "k1"})
    client = QuartOAuth2App(
        QuartIntegration("idp"),
        name="idp",
        client_id="client-1",
        client_secret="y",
        access_token_url=f"{ISSUER}/token",
        # Leftover kwargs become server_metadata: no discovery request.
        issuer=ISSUER,
        jwks=KeySet([key]).as_dict(private=False),
        id_token_signing_alg_values_supported=["RS256"],
    )

    def sign(nonce):
        now = int(time.time())
        claims = {
            "iss": ISSUER,
            "sub": "user-1",
            "aud": "client-1",
            "iat": now,
            "exp": now + 300,
            "nonce": nonce,
            "email": "a.b@mail.com",
        }
        return jwt.encode({"alg": "RS256", "kid": "k1"}, claims, key)

    return client, sign


def _run_callback(client, token, state_data, monkeypatch):
    """Store ``state_data`` under state ``xyz``, then run the callback with
    ``fake_fetch`` returning ``token``. Returns (result, fetch kwargs, session).
    """
    from quart import session as quart_session

    fetched = {}

    async def fake_fetch(**kwargs):
        fetched.update(kwargs)
        return dict(token)

    monkeypatch.setattr(client, "fetch_access_token", fake_fetch)
    app = _make_quart_app()

    async def run():
        async with app.test_request_context(
            "/oidc/idp/callback?code=the-code&state=xyz", method="GET"
        ):
            await client.framework.set_state_data(quart_session, "xyz", state_data)
            result = await client.authorize_access_token()
            return result, dict(quart_session)

    result, session = asyncio.run(run())
    return result, fetched, session


def test_authorize_access_token_validates_id_token_with_stored_nonce(monkeypatch):
    client, sign = _signed_id_token_client()
    token = {"access_token": "at", "token_type": "Bearer", "id_token": sign("n-1")}
    state = {"nonce": "n-1", "redirect_uri": "https://app.example/cb"}

    result, fetched, session = _run_callback(client, token, state, monkeypatch)

    assert result["userinfo"]["sub"] == "user-1"
    assert result["userinfo"]["email"] == "a.b@mail.com"
    # The code and the redirect_uri saved at login go to the token endpoint.
    assert fetched["code"] == "the-code"
    assert fetched["redirect_uri"] == "https://app.example/cb"
    # The state is single-use.
    assert "_state_idp_xyz" not in session


def test_authorize_access_token_rejects_id_token_with_wrong_nonce(monkeypatch):
    """Replay protection: an id_token minted for another login is refused."""
    from joserfc.errors import InvalidClaimError

    client, sign = _signed_id_token_client()
    token = {"access_token": "at", "token_type": "Bearer", "id_token": sign("other")}

    with pytest.raises(InvalidClaimError, match="nonce"):
        _run_callback(client, token, {"nonce": "n-1"}, monkeypatch)


def test_authorize_access_token_without_id_token_has_no_userinfo(monkeypatch):
    client, _sign = _signed_id_token_client()
    token = {"access_token": "at", "token_type": "Bearer"}

    result, _fetched, _session = _run_callback(
        client, token, {"nonce": "n-1"}, monkeypatch
    )

    assert "userinfo" not in result


def test_save_authorize_data_without_state_raises():
    client = _make_oauth2_app()
    with pytest.raises(RuntimeError, match="Missing state"):
        asyncio.run(client.save_authorize_data(redirect_uri="https://app.example/cb"))


# --------------------------------------------------------------------------- #
# Cache-backed state (OAuth(cache=...)): the session holds only a marker
# --------------------------------------------------------------------------- #
class _AsyncCache:
    def __init__(self):
        self.store = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, expires=None):
        self.store[key] = value

    async def delete(self, key):
        self.store.pop(key, None)


def test_cache_state_roundtrip_keeps_data_out_of_the_session():
    cache = _AsyncCache()
    integration = QuartIntegration("idp", cache=cache)
    session = {"user": "kept"}

    async def run():
        await integration.set_state_data(session, "abc", {"nonce": "n"})
        assert "data" not in session["_state_idp_abc"]
        assert "_state_idp_abc" in cache.store
        assert session["user"] == "kept"  # the sweep only touches state keys
        assert await integration.get_state_data(session, "abc") == {"nonce": "n"}
        await integration.clear_state_data(session, "abc")
        assert "_state_idp_abc" not in cache.store
        assert "_state_idp_abc" not in session

    asyncio.run(run())


def test_cache_state_requires_the_session_marker():
    """RFC 6749 10.12: the callback must come from the browser that started
    the login. Valid cached state without that browser's marker is refused.
    """
    cache = _AsyncCache()
    integration = QuartIntegration("idp", cache=cache)

    async def run():
        await integration.set_state_data({}, "abc", {"nonce": "n"})
        assert "_state_idp_abc" in cache.store
        assert await integration.get_state_data({}, "abc") is None
        assert await integration.get_state_data(None, "abc") is None

    asyncio.run(run())


@pytest.mark.parametrize("cached", [None, "not json"], ids=["missing", "corrupt"])
def test_cache_state_unreadable_value_is_none(cached):
    cache = _AsyncCache()
    integration = QuartIntegration("idp", cache=cache)
    session = {"_state_idp_abc": {"exp": time.time() + 60}}
    if cached is not None:
        cache.store["_state_idp_abc"] = cached

    assert asyncio.run(integration.get_state_data(session, "abc")) is None


def test_cache_state_without_session():
    cache = _AsyncCache()
    integration = QuartIntegration("idp", cache=cache)

    async def run():
        await integration.set_state_data(None, "abc", {"nonce": "n"})
        await integration.clear_state_data(None, "abc")
        assert cache.store == {}

    asyncio.run(run())


def test_state_without_cache_or_session_is_none():
    integration = QuartIntegration("idp")
    assert asyncio.run(integration.get_state_data(None, "abc")) is None


def test_oauth_init_app_accepts_cache_and_token_hooks():
    from dash_auth_async.quart_client import OAuth

    def fetch_token(*_a):
        return None

    def update_token(*_a):
        return None

    cache = _AsyncCache()
    oauth = OAuth()
    oauth.init_app(
        _make_quart_app(),
        cache=cache,
        fetch_token=fetch_token,
        update_token=update_token,
    )
    assert oauth.cache is cache
    assert oauth.fetch_token is fetch_token
    assert oauth.update_token is update_token
