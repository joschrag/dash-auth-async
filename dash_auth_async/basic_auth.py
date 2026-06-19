"""Basic (username/password) HTTP authentication for Dash apps."""

import base64
import binascii
import hmac
import logging
from collections.abc import Callable
from typing import cast

from dash import Dash

from .auth import Auth

UserGroups = dict[str, list[str]]


class BasicAuth(Auth):
    """Protect a Dash app with HTTP Basic authentication."""

    def __init__(  # noqa: PLR0913, PLR0917 — configuration constructor
        self,
        app: Dash,
        username_password_list: list | dict | None = None,
        auth_func: Callable | None = None,
        public_routes: list | None = None,
        user_groups: UserGroups | Callable[[str], UserGroups] | None = None,
        secret_key: str | None = None,
    ):
        """Add basic authentication to Dash.

        :param app: Dash app
        :param username_password_list: username:password list, either as a
            list of tuples or a dict
        :param auth_func: python function accepting two string
            arguments (username, password) and returning a
            boolean (True if the user has access otherwise False).
        :param public_routes: list of public routes, routes should follow the
            Flask route syntax
        :param user_groups: a dict or a function returning a dict
            Optional group for each user, allowing to protect routes and
            callbacks depending on user groups
        :param secret_key: Flask secret key
            A string to protect the Flask session, by default None.
            It is required if you need to store the current user
            in the session.
            Generate a secret key in your Python session
            with the following commands:
            >>> import os
            >>> import base64
            >>> base64.b64encode(os.urandom(30)).decode('utf-8')
            Note that you should not do this dynamically:
            you should create a key and then assign the value of
            that key in your code.

        Raises:
            ValueError: if both ``auth_func`` and ``username_password_list``
                are supplied, or if neither is.
        """
        self._auth_func = auth_func
        if isinstance(user_groups, dict):
            self._user_groups_dict: UserGroups | None = cast(UserGroups, user_groups)
            self._user_groups_func: Callable[[str], UserGroups] | None = None
        else:
            self._user_groups_dict = None
            self._user_groups_func = user_groups  # Callable or None after dict excluded

        if self._auth_func is not None:
            if username_password_list is not None:
                raise ValueError(
                    "BasicAuth can only use authorization function "
                    "(auth_func kwarg) or username_password_list, "
                    "it cannot use both."
                )
        elif username_password_list is None:
            raise ValueError(
                "BasicAuth requires username/password map "
                "or user-defined authorization function."
            )
        else:
            self._users = (
                username_password_list
                if isinstance(username_password_list, dict)
                else {k: v for k, v in username_password_list}
            )
        super().__init__(app, public_routes=public_routes)

        # After super().__init__: self.backend now exists, and the auth
        # middleware is registered, so SessionMiddleware (added here) lands
        # outermost on FastAPI — making request.session available to both
        # the auth layer and the Dash callback.
        self.backend.setup_session(app.server, secret_key)

    def is_authorized(self):
        """Return whether the request carries valid Basic credentials.

        Parses the ``Authorization`` header; a missing or malformed header
        returns ``False`` (surfacing as a 401 rather than a 500). On success
        the authenticated user is stored in the session.

        :return: True if the credentials are valid, otherwise False.
        """
        header = self.request.headers.get("Authorization", None)
        if not header:
            return False
        try:
            username_password = base64.b64decode(
                header.split("Basic ")[1], validate=True
            )
            username_password_utf8 = username_password.decode("utf-8")
            username, password = username_password_utf8.split(":", 1)
        except (binascii.Error, UnicodeEncodeError, ValueError, IndexError):
            return False
        authorized = False
        if self._auth_func is not None:
            try:
                authorized = self._auth_func(username, password)
            except Exception:
                logging.exception("Error in authorization function.")
                return False
        else:
            stored_password = self._users.get(username)
            if stored_password is None:
                return authorized
            authorized = hmac.compare_digest(stored_password, password)
        if authorized:
            try:
                self.session["user"] = {"email": username, "groups": []}
                if self._user_groups_dict is not None:
                    self.session["user"]["groups"] = self._user_groups_dict.get(
                        username, []
                    )
                elif self._user_groups_func is not None:
                    self.session["user"]["groups"] = self._user_groups_func(username)
            except RuntimeError:
                logging.warning("Session is not available. Have you set a secret key?")
        return authorized

    def login_request(self):  # noqa: PLR6301 — overrides Auth.login_request
        """Return a 401 response prompting the browser for credentials.

        :return: a ``(body, status, headers)`` tuple challenging the client
            with HTTP Basic authentication.
        """
        return (
            "Login Required",
            401,
            {"WWW-Authenticate": 'Basic realm="User Visible Realm"'},
        )
