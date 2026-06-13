import logging
import os
import re
from typing import Optional, Union, TYPE_CHECKING

import dash
from authlib.integrations.base_client import OAuthError
from authlib.integrations.flask_client import OAuth
from dash_auth_async.auth import Auth
from dash_auth_async.public_routes import get_url_base
from flask import Response
from werkzeug.routing import Map, Rule

from .backends import QuartBackend

if TYPE_CHECKING:
    from authlib.integrations.flask_client.apps import (
        FlaskOAuth1App,
        FlaskOAuth2App,
    )
    from dash_auth_async.quart_client import OAuth as QuartOAuth
    from dash_auth_async.quart_client import QuartOAuth2App


class OIDCAuth(Auth):
    """Implements auth via OpenID."""

    def __init__(
        self,
        app: dash.Dash,
        secret_key: str | None = None,
        force_https_callback: Optional[Union[bool, str]] = None,
        login_route: str = "/oidc/<idp>/login",
        logout_route: str = "/oidc/logout",
        callback_route: str = "/oidc/<idp>/callback",
        idp_selection_route: str | None = None,
        log_signins: bool = False,
        public_routes: Optional[list] = None,
        logout_page: Union[str, Response] | None = None,
        secure_session: bool = False,
    ):
        """Secure a Dash app through OpenID Connect.

        Parameters
        ----------
        app : Dash
            The Dash app to secure
        secret_key : str, optional
            A string to protect the Flask session, by default None.
            Generate a secret key in your Python session
            with the following commands:
            >>> import os
            >>> import base64
            >>> base64.b64encode(os.urandom(30)).decode('utf-8')
            Note that you should not do this dynamically:
            you should create a key and then assign the value of
            that key in your code.
        force_https_callback : Union[bool, str], optional
            Whether to force redirection to https, by default None
            This is useful when the HTTPS termination is upstream of the server
            If a string is passed, this will check for the existence of
            an envvar with that name and force https callback if it exists.
        login_route : str, optional
            The route for the login function, it requires a <idp>
            placeholder, by default "/oidc/<idp>/login".
        logout_route : str, optional
            The route for the logout function, by default "/oidc/logout".
        callback_route : str, optional
            The route for the OIDC redirect URI, it requires a <idp>
            placeholder, by default "/oidc/<idp>/callback".

            NOTE: login_route, logout_route, and callback_route are
            registered directly on the Flask server at the paths given here,
            regardless of any ``url_base_pathname`` or
            ``routes_pathname_prefix`` set on the Dash app. If your app is
            deployed under a prefix (e.g. ``url_base_pathname="/app/"``), the
            OIDC routes still live at the server root (e.g.
            ``/oidc/<idp>/callback``), NOT under the prefix. Configure your
            IDP's redirect URI accordingly.
        idp_selection_route : str, optional
            The route for the IDP selection function, by default None
        log_signins : bool, optional
            Whether to log signins, by default False
        public_routes : list, optional
            List of public routes, routes should follow the
            Flask route syntax
        logout_page : str or Response, optional
            Page seen by the user after logging out,
            by default None which will default to a simple logged out message
        secure_session: bool, optional
            Whether to ensure the session is secure, setting the flasck config
            SESSION_COOKIE_SECURE and SESSION_COOKIE_HTTPONLY to True,
            by default False

        Raises
        ------
        Exception
            Raise an exception if the app.server.secret_key is not defined
        """
        super().__init__(app, public_routes=public_routes)

        if isinstance(force_https_callback, str):
            self.force_https_callback = force_https_callback in os.environ
        elif force_https_callback is not None:
            self.force_https_callback = force_https_callback
        else:
            self.force_https_callback = False

        self.login_route = login_route
        self.logout_route = logout_route
        self.callback_route = callback_route
        self.log_signins = log_signins
        self.idp_selection_route = idp_selection_route
        self.logout_page = logout_page

        if secret_key is not None:
            app.server.secret_key = secret_key

        if app.server.secret_key is None:
            raise RuntimeError("""
                app.server.secret_key is missing.
                Generate a secret key in your Python session
                with the following commands:
                >>> import os
                >>> import base64
                >>> base64.b64encode(os.urandom(30)).decode('utf-8')
                and assign it to the property app.server.secret_key
                (where app is your dash app instance), or pass is as
                the secret_key argument to OIDCAuth.__init__.
                Note that you should not do this dynamically:
                you should create a key and then assign the value of
                that key in your code/via a secret.
                """)

        if secure_session:
            app.server.config["SESSION_COOKIE_SECURE"] = True
            app.server.config["SESSION_COOKIE_HTTPONLY"] = True

        if isinstance(self.backend, QuartBackend):
            # Imported lazily so flask-only installs never import
            # quart/httpx (quart_client raises ImportError without them).
            from dash_auth_async import quart_client

            self.oauth: "OAuth | quart_client.OAuth" = quart_client.OAuth(app.server)
        else:
            self.oauth = OAuth(app.server)

        # Check that the login and callback rules have an <idp> placeholder
        if not re.findall(r"/<idp>(?=/|$)", login_route):
            raise Exception("The login route must contain a <idp> placeholder.")
        if not re.findall(r"/<idp>(?=/|$)", callback_route):
            raise Exception("The callback route must contain a <idp> placeholder.")

        if isinstance(self.backend, QuartBackend):
            login_view = self._login_request_async
            logout_view = self._logout_async
            callback_view = self._callback_async
        else:
            login_view = self.login_request
            logout_view = self.logout
            callback_view = self.callback

        app.server.add_url_rule(
            login_route,
            endpoint="oidc_login",
            view_func=login_view,
            methods=["GET"],
        )
        app.server.add_url_rule(
            logout_route,
            endpoint="oidc_logout",
            view_func=logout_view,
            methods=["GET"],
        )
        app.server.add_url_rule(
            callback_route,
            endpoint="oidc_callback",
            view_func=callback_view,
            methods=["GET"],
        )

    def register_provider(self, idp_name: str, **kwargs):
        """Register an OpenID Connect provider.

        :param idp_name: The name of the provider
        :param kwargs: Keyword arguments passed to OAuth.register.
            See https://docs.authlib.org/en/latest/client/flask.html for
            additional details.
            Typical keyword arguments for OIDC include:
            * client_id
            * client_secret
            * server_metadata_url
            * token_endpoint_auth_method
            * client_kwargs (defaults to {"scope": "openid email"})
        """
        if not re.match(r"^[\w\-\. ]+$", idp_name):
            raise ValueError(
                "`idp_name` should only contain letters, numbers, hyphens, "
                "underscores, periods and spaces"
            )
        client_kwargs = kwargs.pop("client_kwargs", {})
        client_kwargs.setdefault("scope", "openid email")
        self.oauth.register(idp_name, client_kwargs=client_kwargs, **kwargs)

    def get_oauth_client(self, idp: str):
        """Get the OAuth client."""
        if idp not in self.oauth._registry:
            raise ValueError(f"'{idp}' is not a valid registered idp")

        client: Union[FlaskOAuth1App, FlaskOAuth2App, QuartOAuth2App] = (
            self.oauth.create_client(idp)
        )
        return client

    def get_oauth_kwargs(self, idp: str):
        """Get the OAuth kwargs."""
        if idp not in self.oauth._registry:
            raise ValueError(f"'{idp}' is not a valid registered idp")

        kwargs: dict = self.oauth._registry[idp][1]
        return kwargs

    def _resolve_idp(self, idp: Optional[str]):
        """Resolve which idp to use for login.

        Returns ``(idp, None)`` when a provider could be determined, or
        ``(None, response)`` when the caller should return ``response``
        instead (idp-selection redirect or a 400). Shared by the sync and
        async login views so selection behavior cannot drift.
        """
        if idp in self.oauth._registry:
            return idp, None
        # If only one provider is registered, we don't need to
        # ask the user to pick one, just use the one
        if len(self.oauth._registry) == 1:
            return next(iter(self.oauth._registry)), None
        # If there are several providers and a `idp_selection_route`
        # was provided, redirect to it.
        if self.idp_selection_route:
            return None, self.backend.redirect(self.idp_selection_route)
        return None, (
            "Several OAuth providers are registered. Please choose one.",
            400,
        )

    def _create_redirect_uri(self, idp: str):
        """Create the redirect uri based on callback endpoint and idp."""
        if self.force_https_callback:
            redirect_uri = self.backend.url_for(
                "oidc_callback", idp=idp, _external=True, _scheme="https"
            )
        else:
            redirect_uri = self.backend.url_for(
                "oidc_callback", idp=idp, _external=True
            )
        host = self.request.headers.get("X-Forwarded-Host")
        if host:
            redirect_uri = redirect_uri.replace(self.request.host, host, 1)
        return redirect_uri

    def login_request(self, idp: str | None = None):
        """Start the login process.

        On the Quart path this returns a coroutine (both the route and the
        before-request hook await it); on Flask it returns the response.
        """
        # `idp` can be none here as login_request is called
        # without arguments in the before_request hook
        if isinstance(self.backend, QuartBackend):
            return self._login_request_async(idp)

        idp, response = self._resolve_idp(idp)
        if response is not None:
            return response

        redirect_uri = self._create_redirect_uri(idp)
        oauth_client = self.get_oauth_client(idp)
        oauth_kwargs = self.get_oauth_kwargs(idp)
        return oauth_client.authorize_redirect(
            redirect_uri,
            **oauth_kwargs.get("authorize_redirect_kwargs", {}),
        )

    async def _login_request_async(self, idp: str | None = None):
        """Async login view for the Quart path."""
        idp, response = self._resolve_idp(idp)
        if response is not None:
            return response

        redirect_uri = self._create_redirect_uri(idp)
        oauth_client = self.get_oauth_client(idp)
        oauth_kwargs = self.get_oauth_kwargs(idp)
        return await oauth_client.authorize_redirect(
            redirect_uri,
            **oauth_kwargs.get("authorize_redirect_kwargs", {}),
        )

    def logout(self):  # pylint: disable=C0116
        """Logout the user."""
        self.session.clear()
        base_url = get_url_base(self.app) or "/"
        page = (
            self.logout_page
            or f"""
        <div style="display: flex; flex-direction: column;
        gap: 0.75rem; padding: 3rem 5rem;">
            <div>Logged out successfully</div>
            <div><a href="{base_url}">Go back</a></div>
        </div>
        """
        )
        return page

    async def _logout_async(self):
        """Async logout view for the Quart path; the body is sync."""
        return self.logout()

    def callback(self, idp: str):  # pylint: disable=C0116
        """Handle the OIDC dance and post-login actions."""
        if idp not in self.oauth._registry:
            return f"'{idp}' is not a valid registered idp", 400

        oauth_client = self.get_oauth_client(idp)
        oauth_kwargs = self.get_oauth_kwargs(idp)
        try:
            token = oauth_client.authorize_access_token(
                **oauth_kwargs.get("authorize_token_kwargs", {}),
            )
        except OAuthError as err:
            return str(err), 401

        user = token.get("userinfo")
        return self.after_logged_in(user, idp, token)

    async def _callback_async(self, idp: str):
        """Async OIDC callback view for the Quart path."""
        if idp not in self.oauth._registry:
            return f"'{idp}' is not a valid registered idp", 400

        oauth_client = self.get_oauth_client(idp)
        oauth_kwargs = self.get_oauth_kwargs(idp)
        try:
            token = await oauth_client.authorize_access_token(
                **oauth_kwargs.get("authorize_token_kwargs", {}),
            )
        except OAuthError as err:
            return str(err), 401

        user = token.get("userinfo")
        return self.after_logged_in(user, idp, token)

    def after_logged_in(self, user: Optional[dict], idp: str, token: dict):
        """
        Post-login actions after successful OIDC authentication.
        For example, allows to pass custom attributes to the user session:
        class MyOIDCAuth(OIDCAuth):
            def after_logged_in(self, user, idp, token):
                if user:
                    user["params"] = value1
                return super().after_logged_in(user, idp, token)
        """
        if user:
            self.session["user"] = user
            self.session["idp"] = idp
            oauth_scope = self.get_oauth_client(idp).client_kwargs["scope"]
            if "offline_access" in oauth_scope:
                self.session["refresh_token"] = token.get("refresh_token")
            if self.log_signins:
                logging.info("User %s is logging in.", user.get("email"))

        return self.backend.redirect(get_url_base(self.app) or "/")

    def is_authorized(self):  # pylint: disable=C0116
        """Check whether ther user is authenticated."""

        map_adapter = Map(
            [
                Rule(x)
                for x in [
                    self.login_route,
                    self.logout_route,
                    self.callback_route,
                    self.idp_selection_route,
                ]
                if x
            ]
        ).bind("")
        return map_adapter.test(self.request.path) or "user" in self.session


def get_oauth(app: dash.Dash | None = None) -> "Union[OAuth, QuartOAuth]":
    """Retrieve the OAuth object.

    :param app: dash.Dash
        Dash app or None, if None the current app is used
        calling `dash.get_app()`
    """
    if app is None:
        app = dash.get_app()

    extensions = getattr(app.server, "extensions", {})
    for extension_key in (
        "authlib.integrations.flask_client",
        "authlib.integrations.quart_client",
    ):
        oauth = extensions.get(extension_key)
        if oauth is not None:
            return oauth

    raise RuntimeError(
        "OAuth object is not yet defined. `OIDCAuth(app, **kwargs)` needs "
        "to be run before `get_oauth` is called."
    )
