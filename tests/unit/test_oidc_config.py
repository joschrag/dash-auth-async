"""``OIDCAuth`` configuration checks, provider lookup and ``get_oauth``.

These run the real constructor on the Flask backend; no IdP is contacted
(registering a provider stores its kwargs, discovery happens on first login).
"""

import logging

import dash
import pytest
from dash import Dash

from dash_auth_async import get_oauth
from dash_auth_async.oidc_auth import OIDCAuth

pytestmark = pytest.mark.usefixtures("reset_active_backend")

SECRET = "test-secret-key"


def _auth(**kwargs):
    kwargs.setdefault("secret_key", SECRET)
    return OIDCAuth(Dash(__name__), **kwargs)


@pytest.mark.parametrize(
    ("value", "env", "expected"),
    [
        ("FORCE_HTTPS_FLAG", {"FORCE_HTTPS_FLAG": "1"}, True),
        ("FORCE_HTTPS_FLAG", {}, False),
        (True, {}, True),
        (None, {}, False),
    ],
    ids=["env-name-set", "env-name-unset", "bool", "default"],
)
def test_force_https_callback_accepts_env_var_name_or_bool(
    monkeypatch, value, env, expected
):
    monkeypatch.delenv("FORCE_HTTPS_FLAG", raising=False)
    for name, val in env.items():
        monkeypatch.setenv(name, val)
    assert _auth(force_https_callback=value).force_https_callback is expected


def test_missing_secret_key_refuses_to_start():
    """Without a key the session (and so the login) can't work: fail at setup."""
    with pytest.raises(RuntimeError, match="secret_key is missing"):
        OIDCAuth(Dash(__name__))


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"login_route": "/oidc/login"}, "login route"),
        ({"callback_route": "/oidc/callback"}, "callback route"),
    ],
    ids=["login", "callback"],
)
def test_routes_must_contain_the_idp_placeholder(kwargs, match):
    with pytest.raises(Exception, match=match):
        _auth(**kwargs)


def test_register_provider_rejects_unsafe_names():
    auth = _auth()
    with pytest.raises(ValueError, match="idp_name"):
        auth.register_provider("bad/name", client_id="x")


def test_unknown_idp_lookups_raise():
    auth = _auth()
    auth.register_provider("idp", client_id="x")
    with pytest.raises(ValueError, match="not a valid registered idp"):
        auth.get_oauth_client("other")
    with pytest.raises(ValueError, match="not a valid registered idp"):
        auth.get_oauth_kwargs("other")


def test_several_providers_redirect_to_the_selection_page():
    auth = _auth(idp_selection_route="/choose")
    auth.register_provider("a", client_id="x")
    auth.register_provider("b", client_id="y")
    with auth.app.server.test_request_context("/"):
        idp, response = auth._resolve_idp(None)
    assert idp is None
    assert response.status_code == 302
    assert response.headers["Location"] == "/choose"


def test_after_logged_in_without_user_writes_no_session():
    auth = _auth()
    with auth.app.server.test_request_context("/"):
        response = auth.after_logged_in(None, "idp", {})
        assert "user" not in auth.session
        assert "idp" not in auth.session
    assert response.status_code == 302


def test_after_logged_in_logs_signins_when_enabled(caplog):
    auth = _auth(log_signins=True)
    with (
        auth.app.server.test_request_context("/"),
        caplog.at_level(logging.INFO),
    ):
        auth.after_logged_in({"email": "a.b@mail.com"}, "idp", {})
    assert "a.b@mail.com is logging in" in caplog.text


def test_get_oauth_defaults_to_the_current_app():
    auth = _auth()
    assert dash.get_app() is auth.app
    assert get_oauth() is auth.oauth
    assert get_oauth(auth.app) is auth.oauth


def test_get_oauth_before_oidcauth_raises():
    with pytest.raises(RuntimeError, match="not yet defined"):
        get_oauth(Dash(__name__))
