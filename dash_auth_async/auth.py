from __future__ import absolute_import
from abc import ABC, abstractmethod
from typing import Optional

from dash import Dash
from .backends import Backend, detect_backend, set_active_backend

from .public_routes import (
    add_public_routes,
    get_public_callbacks,
    get_public_routes,
    get_url_base,
)


class Auth(ABC):
    def __init__(
        self,
        app: Dash,
        public_routes: Optional[list] = None,
        backend: Optional[Backend] = None,
        **obsolete,
    ):
        """Auth base class for authentication in Dash.

        :param app: Dash app
        :param public_routes: list of public routes, routes should follow the
            Flask route syntax
        """

        # Deprecated arguments
        if obsolete:
            raise TypeError(f"Auth got unexpected keyword arguments: {list(obsolete)}")

        self.app = app
        self.backend = backend if backend is not None else detect_backend(app.server)
        set_active_backend(self.backend)
        self._protect()
        if public_routes is not None:
            add_public_routes(app, public_routes)

    @property
    def request(self):
        return self.backend.request

    @property
    def session(self):
        return self.backend.session

    def _callback_path(self) -> str:
        """Path of Dash's callback route, including any URL base prefix."""
        url_base = get_url_base(self.app)
        return f"{url_base.rstrip('/')}/_dash-update-component"

    def _protect(self):
        """Add a before_request authentication check on all routes.

        The authentication check will pass if either
            * The endpoint is marked as public via `add_public_routes`
            * The request is authorised by `Auth.is_authorised`
        """
        self.backend.register_auth_hook(
            self.app.server,
            lambda path: path == self._callback_path(),
            self._authorize,
        )

    def _authorize(self, path: str, body: Optional[dict]):
        """Decide whether a request may proceed.

        Pure decision logic shared by all backends: receives the request
        path and the parsed JSON body (only provided for the Dash callback
        route). Returns None to allow the request, or a login response.
        """

        public_routes = get_public_routes(self.app)
        public_callbacks = get_public_callbacks(self.app)
        if path == self._callback_path():
            # Treat a missing or unparseable body as unauthorised rather
            # than crashing with AttributeError/KeyError → 500.
            if not body:
                return self.login_request()

            # Check whether the callback is marked as public
            if body.get("output") in public_callbacks:
                return None

            # Check whether the callback has an input using the pathname,
            # such a callback will be a routing callback and the pathname
            # should be checked against the public routes
            pathname = next(
                (
                    inp.get("value")
                    for inp in body["inputs"]
                    if isinstance(inp, dict) and inp.get("property") == "pathname"
                ),
                None,
            )
            if pathname and public_routes.test(pathname):
                return None

        # If the route is not a callback route, check whether the path
        # matches a public route, or whether the request is authorised
        if public_routes.test(path) or self.is_authorized():
            return None

        # Otherwise, ask the user to log in
        return self.login_request()

    @abstractmethod
    def is_authorized(self):
        pass

    @abstractmethod
    def login_request(self):
        pass
