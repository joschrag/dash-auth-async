"""``OIDCAuth`` must not persist the IdP refresh token in the session cookie.

Flask/Quart/Starlette session cookies are signed, not encrypted: anyone holding
the cookie can decode it. A refresh token is a long-lived IdP credential that
outlives logout, and nothing in the library ever read it back.
"""

from types import SimpleNamespace

import pytest
from dash import Dash

from dash_auth_async.oidc_auth import OIDCAuth

pytestmark = pytest.mark.usefixtures("reset_active_backend")


def test_offline_access_login_does_not_store_the_refresh_token():
    """Regression: with the ``offline_access`` scope, ``after_logged_in`` wrote
    ``token["refresh_token"]`` into ``session["refresh_token"]``.

    Built via ``__new__`` to exercise the method without the OIDC provider
    wiring ``OIDCAuth.__init__`` requires.
    """
    auth = object.__new__(OIDCAuth)
    auth.app = Dash(__name__)
    auth.backend = SimpleNamespace(session={}, redirect=lambda url: url)
    auth.log_signins = False
    auth.get_oauth_client = lambda idp: SimpleNamespace(
        client_kwargs={"scope": "openid email offline_access"}
    )

    user = {"email": "a.b@mail.com"}
    token = {"userinfo": user, "refresh_token": "ABCDEF"}
    auth.after_logged_in(user, "idp", token)

    assert auth.backend.session["user"] == user
    assert "refresh_token" not in auth.backend.session
    assert "ABCDEF" not in repr(auth.backend.session)
