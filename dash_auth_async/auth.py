"""Framework-agnostic authentication base class for Dash."""

from abc import ABC, abstractmethod

from dash import Dash

from .backends import Backend, detect_backend, set_active_backend
from .public_routes import (
    add_public_routes,
    get_public_callbacks,
    get_public_routes,
    get_url_base,
)
from .websocket_auth import enable_ws_auth


class Auth(ABC):
    """Base class holding the framework-agnostic auth decision logic."""

    def __init__(
        self,
        app: Dash,
        public_routes: list | None = None,
        backend: Backend | None = None,
        **obsolete,
    ):
        """Auth base class for authentication in Dash.

        :param app: Dash app
        :param public_routes: list of public routes, routes should follow the
            Flask route syntax

        Raises:
            TypeError: if any deprecated/unexpected keyword argument is passed.
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
        enable_ws_auth(self, app)

    @property
    def request(self):
        """The active backend's request proxy.

        Returns:
            The framework-specific request object for the current request.
        """
        return self.backend.request

    @property
    def session(self):
        """The active backend's session proxy.

        Returns:
            The framework-specific session mapping for the current request.
        """
        return self.backend.session

    def _callback_path(self) -> str:
        """Path of Dash's callback route, including any URL base prefix.

        Returns:
            The fully-qualified ``_dash-update-component`` path.
        """
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

    def _authorize(self, path: str, body: dict | None):
        """Decide whether a request may proceed.

        Pure decision logic shared by all backends: receives the request
        path and the parsed JSON body (only provided for the Dash callback
        route).

        Returns:
            None to allow the request, or a login response to reject it.
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

    def authorize_ws(self, payload: dict | None, user: dict | None) -> bool:
        """Decide whether a WebSocket callback_request may run.

        Mirrors ``_authorize``'s public checks but, because there is no
        ``request`` context over a WebSocket, treats the presence of an
        authenticated session user as proof of login (the session cookie sent
        at the handshake already proves it).

        :param payload: the callback payload (same shape as the HTTP
            ``_dash-update-component`` body: ``output``, ``inputs``, ...)
        :param user: ``session["user"]`` or ``None``

        Returns:
            True to allow the callback, False to reject the connection.
        """
        payload = payload or {}
        public_callbacks = get_public_callbacks(self.app)
        if payload.get("output") in public_callbacks:
            return True

        public_routes = get_public_routes(self.app)
        pathname = next(
            (
                inp.get("value")
                for inp in payload.get("inputs", [])
                if isinstance(inp, dict) and inp.get("property") == "pathname"
            ),
            None,
        )
        if pathname and public_routes.test(pathname):
            return True

        return user is not None

    @abstractmethod
    def is_authorized(self):
        """Return whether the current request is authenticated."""

    @abstractmethod
    def login_request(self):
        """Return the response that challenges an unauthenticated client."""
