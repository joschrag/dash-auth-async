"""Authlib OAuth integration for Quart servers.

authlib ships no quart_client; this module is the Quart counterpart of
``authlib.integrations.flask_client``, assembled from authlib's
framework-agnostic async mixins (the same building blocks as
``starlette_client``, which serves as the template). Only OAuth2/OIDC is
implemented: OIDCAuth never issues OAuth1 flows.

All protocol-critical behavior (discovery, JWKS, token exchange, id_token
and nonce validation, PKCE) lives in the inherited authlib mixins; this
module only owns session state, callback-param access, and redirects.
"""

from __future__ import annotations

import json
import time
from typing import Any

from authlib.integrations.base_client import (
    BaseApp,
    BaseOAuth,
    FrameworkIntegration,
    OAuthError,
)
from authlib.integrations.base_client.async_app import AsyncOAuth2Mixin
from authlib.integrations.base_client.async_openid import AsyncOpenIDMixin
from werkzeug.local import LocalProxy

try:
    import quart
    from authlib.integrations.httpx_client import AsyncOAuth2Client
except ImportError as exc:  # pragma: no cover - exercised only on broken installs
    raise ImportError(
        "dash_auth_async.quart_client requires Quart and httpx. "
        "Install them with `pip install dash-auth-async[quart]`."
    ) from exc

__all__ = [
    "OAuth",
    "OAuthError",
    "QuartIntegration",
    "QuartOAuth2App",
]


class QuartIntegration(FrameworkIntegration):
    """Session-state handling for Quart, copied from StarletteIntegration.

    The dict-like Quart session is passed in by the app mixin; state
    entries carry an expiry and stale ``_state_{name}_*`` keys are swept
    on each new login attempt so abandoned flows cannot grow the signed
    session cookie past the ~4 KB browser limit.
    """

    async def _get_cache_data(self, key):
        value = await self.cache.get(key)  # type: ignore
        if not value:
            return None
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return None

    async def get_state_data(
        self, session: dict[str, Any] | None, state: str
    ) -> dict[str, Any] | None:
        """Return the stored authorization state data, or None if absent.

        Returns:
            The state ``data`` payload, or None when not found or unverified.
        """
        key = f"_state_{self.name}_{state}"
        if self.cache:
            # require a session-bound marker to prove the callback
            # originates from the user-agent that started the flow
            # (RFC 6749 section 10.12)
            if session is None or session.get(key) is None:
                return None
            value = await self._get_cache_data(key)
        elif session is not None:
            value = session.get(key)
        else:
            value = None

        if value:
            return value.get("data")
        return None

    async def set_state_data(
        self, session: dict[str, Any] | None, state: str, data: Any
    ):
        """Persist authorization state data, sweeping stale state keys."""
        key_prefix = f"_state_{self.name}_"
        key = f"{key_prefix}{state}"
        now = time.time()
        if self.cache:
            await self.cache.set(key, json.dumps({"data": data}), self.expires_in)
            if session is not None:
                # clear old state data to avoid session size growing
                for old_key in list(session.keys()):
                    if old_key.startswith(key_prefix):
                        session.pop(old_key)
                session[key] = {"exp": now + self.expires_in}
        elif session is not None:
            # clear old state data to avoid session size growing
            for old_key in list(session.keys()):
                if old_key.startswith(key_prefix):
                    session.pop(old_key)
            session[key] = {"data": data, "exp": now + self.expires_in}

    async def clear_state_data(self, session: dict[str, Any] | None, state: str):
        """Remove the stored authorization state data for ``state``."""
        key = f"_state_{self.name}_{state}"
        if self.cache:
            await self.cache.delete(key)
        if session is not None:
            session.pop(key, None)
            self._clear_session_state(session)

    def update_token(self, token, refresh_token=None, access_token=None):
        """No-op token-update hook required by the authlib interface."""

    @staticmethod
    def load_config(oauth, name, params):
        """Read ``{NAME}_{PARAM}`` config values into a dict.

        Returns:
            The mapping of requested params present in the app config.
        """
        rv = {}
        for k in params:
            conf_key = f"{name}_{k}".upper()
            v = oauth.app.config.get(conf_key, None)
            if v is not None:
                rv[k] = v
        return rv


class AsyncQuartAppMixin:
    """Flask-shaped but async entry points using Quart's context locals."""

    async def save_authorize_data(self, **kwargs):
        state = kwargs.pop("state", None)
        if state:
            await self.framework.set_state_data(quart.session, state, kwargs)  # type: ignore
        else:
            raise RuntimeError("Missing state value")

    async def authorize_redirect(self, redirect_uri=None, **kwargs):
        """Create a HTTP Redirect for the Authorization Endpoint.

        :param redirect_uri: Callback or redirect URI for authorization.
        :param kwargs: Extra parameters to include.

        Returns:
            A Quart redirect response.
        """
        rv = await self.create_authorization_url(redirect_uri, **kwargs)  # type: ignore
        await self.save_authorize_data(redirect_uri=redirect_uri, **rv)
        return quart.redirect(rv["url"])


class QuartOAuth2App(AsyncQuartAppMixin, AsyncOAuth2Mixin, AsyncOpenIDMixin, BaseApp):
    """OAuth2/OIDC app for the Quart backend."""

    client_cls = AsyncOAuth2Client

    async def authorize_access_token(self, **kwargs):
        """Fetch the access token in one step.

        Only the GET callback shape is handled: OIDCAuth registers the
        callback route with methods=["GET"] exclusively.

        Returns:
            A token dict, including ``userinfo`` when an id_token is present.

        Raises:
            OAuthError: if the IdP returned an error in the callback.
        """
        error = quart.request.args.get("error")
        if error:
            description = quart.request.args.get("error_description")
            raise OAuthError(error=error, description=description)

        params = {
            "code": quart.request.args.get("code"),
            "state": quart.request.args.get("state"),
        }

        state_data = await self.framework.get_state_data(
            quart.session, params.get("state")
        )
        await self.framework.clear_state_data(quart.session, params.get("state"))
        # raises MismatchingStateError (an OAuthError) when state_data is None
        params = self._format_state_params(state_data, params)

        claims_options = kwargs.pop("claims_options", None)
        claims_cls = kwargs.pop("claims_cls", None)
        leeway = kwargs.pop("leeway", 120)
        token = await self.fetch_access_token(**params, **kwargs)

        if "id_token" in token and "nonce" in state_data:
            userinfo = await self.parse_id_token(
                token,
                nonce=state_data["nonce"],
                claims_options=claims_options,
                claims_cls=claims_cls,
                leeway=leeway,
            )
            token["userinfo"] = userinfo
        return token


class OAuth(BaseOAuth):
    """OAuth registry for Quart, mirroring flask_client.OAuth."""

    oauth2_client_cls = QuartOAuth2App
    framework_integration_cls = QuartIntegration

    def __init__(self, app=None, cache=None, fetch_token=None, update_token=None):
        """Create the registry, optionally binding a Quart app immediately."""
        super().__init__(
            cache=cache, fetch_token=fetch_token, update_token=update_token
        )
        self.app = app
        if app:
            self.init_app(app)

    def init_app(self, app, cache=None, fetch_token=None, update_token=None):
        """Initialize lazily for a Quart app (application factory pattern)."""
        self.app = app
        if cache is not None:
            self.cache = cache
        if fetch_token:
            self.fetch_token = fetch_token
        if update_token:
            self.update_token = update_token

        app.extensions = getattr(app, "extensions", {})
        app.extensions["authlib.integrations.quart_client"] = self

    def create_client(self, name):
        """Create the OAuth client registered under ``name``.

        Returns:
            The instantiated OAuth client.

        Raises:
            RuntimeError: if no Quart app has been initialised.
        """
        if not self.app:
            raise RuntimeError("OAuth is not init with Quart app.")
        return super().create_client(name)

    def register(self, name, overwrite=False, **kwargs):
        """Register an OAuth provider and return its client.

        Returns:
            The client, or a LocalProxy that lazily creates it when no app
            is bound yet.
        """
        self._registry[name] = (overwrite, kwargs)
        if self.app:
            return self.create_client(name)
        return LocalProxy(lambda: self.create_client(name))
