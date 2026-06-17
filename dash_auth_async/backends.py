"""Framework adapters isolating Flask/Quart-specific request and session I/O."""

from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from collections.abc import Callable, MutableMapping
from contextvars import ContextVar
from typing import Any

import flask

try:
    import quart

    HAS_QUART = True
except ImportError:
    quart: Any = None
    HAS_QUART = False

try:
    import fastapi
    from starlette.middleware.sessions import SessionMiddleware
    from starlette.requests import Request as StarletteRequest
    from starlette.responses import (
        PlainTextResponse,
        RedirectResponse,
        Response as StarletteResponse,
    )

    HAS_FASTAPI = True
except ImportError:
    fastapi: Any = None
    StarletteRequest: Any = None
    SessionMiddleware: Any = None
    HAS_FASTAPI = False


# dash-auth-async owns its own request ContextVar, set in its own ASGI
# middleware — independent of Dash's private get_current_request.
_current_request_var: ContextVar = ContextVar("dash_auth_request", default=None)


class Backend(ABC):
    """Framework adapter isolating everything Flask/Quart-specific.

    The auth decision logic is a pure function of (path, body); backends
    own the I/O around it: hook registration, body parsing, and the
    request/session proxies.
    """

    request: Any
    session: MutableMapping

    @abstractmethod
    def has_request_context(self) -> bool:
        """Whether a request context is currently active."""

    @abstractmethod
    def register_auth_hook(
        self,
        server,
        needs_body: Callable[[str], bool],
        decide: Callable[[str, dict | None], Any],
    ) -> None:
        """Register a before-request auth hook on the server.

        :param server: the Flask or Quart server instance
        :param needs_body: whether the JSON body must be parsed for this
            request path (evaluated per request)
        :param decide: pure decision function receiving
            (path, parsed_body_or_None); returns None to allow the request
            or a response value to short-circuit it
        """

    @abstractmethod
    def url_for(self, endpoint: str, **values) -> str:
        """Build a URL for the given endpoint on this backend."""

    @abstractmethod
    def redirect(self, location: str) -> Any:
        """Return a redirect response to the given location."""

    # --- Operations that diverge on FastAPI; defaults reproduce the
    # --- Flask/Quart behavior so those backends inherit unchanged. These
    # --- are concrete interface defaults, not all of which use `self`, so
    # --- PLR6301 (no-self-use) is suppressed where that applies.

    def coerce_response(self, result: Any) -> Any:  # noqa: PLR6301
        """Convert an ``_authorize`` return into a real response.

        Flask and Quart accept ``(body, status, headers)`` tuples, bare
        strings, and framework responses natively, so the default is a
        pass-through. FastAPI overrides this to build a Starlette response.

        Returns:
            The response value unchanged.
        """
        return result

    def setup_session(self, server, secret_key: str | None) -> None:  # noqa: PLR6301
        """Install session support on the server.

        Flask/Quart store a ``secret_key`` attribute. FastAPI overrides
        this to add ``SessionMiddleware``.
        """
        if secret_key is not None:
            server.secret_key = secret_key

    def session_configured(self, server) -> bool:  # noqa: PLR6301
        """Whether the server can store a session.

        Returns:
            True if a session secret is configured.
        """
        return getattr(server, "secret_key", None) is not None

    def current_host(self) -> str:
        """Host (netloc) of the active request, for proxy host rewrites.

        Returns:
            The request host string.
        """
        return self.request.host

    def add_route(  # noqa: PLR6301
        self, server, rule: str, view_func, endpoint: str, methods
    ) -> None:
        """Register an OIDC route on the server."""
        server.add_url_rule(
            rule, endpoint=endpoint, view_func=view_func, methods=methods
        )

    def make_oauth(self, server) -> Any:  # noqa: PLR6301
        """Build the authlib OAuth registry for this backend.

        Returns:
            A flask_client ``OAuth`` registry bound to ``server``.
        """
        from authlib.integrations.flask_client import OAuth  # noqa: PLC0415

        return OAuth(server)

    def store_config(self, server, key: str, value: Any) -> None:  # noqa: PLR6301
        """Stash an app-scoped config value (public routes/callbacks).

        Flask/Quart expose a dict-like ``server.config``. FastAPI has no
        such attribute and overrides this to use ``server.state``.
        """
        server.config[key] = value

    def read_config(  # noqa: PLR6301
        self, server, key: str, default: Any = None
    ) -> Any:
        """Read an app-scoped config value set by :meth:`store_config`.

        Returns:
            The stored value, or ``default`` when unset.
        """
        return server.config.get(key, default)


class FlaskBackend(Backend):
    """Backend adapter for a Flask server."""

    # Properties, not class attributes: ABCMeta probes every namespace
    # value for __isabstractmethod__ at class creation, which unwraps
    # the context-local proxies outside any request and raises.
    @property
    def request(self) -> Any:
        """Flask's request context-local proxy.

        Returns:
            The Flask request proxy.
        """
        return flask.request

    @property
    def session(self) -> MutableMapping:
        """Flask's session mapping.

        Returns:
            The Flask session proxy.
        """
        return flask.session

    # The methods below are thin adapters over module-level framework
    # functions; they must stay instance methods to satisfy the Backend
    # interface, so PLR6301 (no-self-use) is suppressed on each.
    def has_request_context(self) -> bool:  # noqa: PLR6301
        """Whether a Flask request context is currently active.

        Returns:
            True if a request context is active.
        """
        return flask.has_request_context()

    def register_auth_hook(self, server, needs_body, decide) -> None:  # noqa: PLR6301
        """Register the before-request auth hook on a Flask server."""

        @server.before_request
        def before_request_auth():
            body = (
                flask.request.get_json(silent=True)
                if needs_body(flask.request.path)
                else None
            )
            return decide(flask.request.path, body)

    def url_for(self, endpoint: str, **values) -> str:  # noqa: PLR6301
        """Build a URL for a Flask endpoint.

        Returns:
            The URL string for ``endpoint``.
        """
        return flask.url_for(endpoint, **values)

    def redirect(self, location: str) -> Any:  # noqa: PLR6301
        """Build a Flask redirect response to ``location``.

        Returns:
            A Flask redirect response.
        """
        return flask.redirect(location)


class QuartBackend(Backend):
    """Backend adapter for a Quart (async) server."""

    def __init__(self) -> None:
        """Create the Quart backend, requiring the optional ``quart`` extra.

        Raises:
            ImportError: if Quart is not installed.
        """
        if quart is None:
            raise ImportError(
                "Quart is not installed. Please install it with `pip install quart` "
                "or `pip install dash[quart]` to use the Quart backend."
            )

    @property
    def request(self) -> Any:
        """Quart's request context-local proxy.

        Returns:
            The Quart request proxy.
        """
        return quart.request

    @property
    def session(self) -> MutableMapping:
        """Quart's session mapping.

        Returns:
            The Quart session proxy.
        """
        return quart.session

    # The methods below are thin adapters over module-level framework
    # functions; they must stay instance methods to satisfy the Backend
    # interface, so PLR6301 (no-self-use) is suppressed on each.
    def has_request_context(self) -> bool:  # noqa: PLR6301
        """Whether a Quart request context is currently active.

        Returns:
            True if a request context is active.
        """
        return quart.has_request_context()

    def register_auth_hook(self, server, needs_body, decide) -> None:  # noqa: PLR6301
        """Register the before-request auth hook on a Quart server.

        Awaits both the request body and the (possibly coroutine) decision so
        async auth logic is preserved.
        """

        @server.before_request
        async def before_request_auth():
            body = (
                await quart.request.get_json(silent=True)
                if needs_body(quart.request.path)
                else None
            )
            result = decide(quart.request.path, body)
            if inspect.isawaitable(result):
                return await result
            return result

    def url_for(self, endpoint: str, **values) -> str:  # noqa: PLR6301
        """Build a URL for a Quart endpoint.

        Returns:
            The URL string for ``endpoint``.
        """
        return quart.url_for(endpoint, **values)

    def redirect(self, location: str) -> Any:  # noqa: PLR6301
        """Build a Quart redirect response to ``location``.

        Returns:
            A Quart redirect response.
        """
        return quart.redirect(location)

    def make_oauth(self, server) -> Any:  # noqa: PLR6301
        """Build the authlib OAuth registry for the Quart backend.

        Returns:
            A custom Quart ``OAuth`` registry bound to ``server``.
        """
        # Imported lazily so flask-only installs never import quart/httpx.
        from dash_auth_async import quart_client  # noqa: PLC0415

        return quart_client.OAuth(server)


class FastAPIBackend(Backend):
    """Adapter for Dash's FastAPI backend (Dash 4.2+).

    Unlike Flask/Quart there is no global request/session proxy: Starlette
    passes the request explicitly. This backend resolves the active request
    from a ContextVar set by its own ASGI auth middleware, and reads the
    session off ``request.session`` (populated by SessionMiddleware).
    """

    def __init__(self) -> None:
        """Create the FastAPI backend, requiring the optional ``fastapi`` extra.

        Raises:
            ImportError: if FastAPI is not installed.
        """
        if not HAS_FASTAPI:
            raise ImportError(
                "FastAPI is not installed. Please install it with "
                "`pip install dash-auth-async[fastapi]` to use the FastAPI backend."
            )

    @property
    def request(self) -> Any:
        """The active Starlette request, resolved from the ContextVar.

        Returns:
            The current request, or None outside a request context.
        """
        return _current_request_var.get()

    @property
    def session(self) -> MutableMapping:
        """The session mapping off the active request.

        Returns:
            The Starlette session mapping.

        Raises:
            RuntimeError: if SessionMiddleware is not installed.
        """
        try:
            return self.request.session
        except AssertionError as exc:
            # Starlette asserts SessionMiddleware is installed. Translate to
            # RuntimeError so existing `except RuntimeError` guards behave
            # identically to the Flask path.
            raise RuntimeError(
                "Session is not available. Have you set a secret key?"
            ) from exc

    def has_request_context(self) -> bool:  # noqa: PLR6301
        """Whether a request is currently bound to the ContextVar.

        Returns:
            True if a request context is active.
        """
        return _current_request_var.get() is not None

    def url_for(self, endpoint: str, **values) -> str:
        """Build an absolute URL for a Starlette endpoint.

        Maps the Flask-style ``_external``/``_scheme`` kwargs used by
        ``OIDCAuth._create_redirect_uri`` onto Starlette's ``url_for``.

        Returns:
            The URL string for ``endpoint``.
        """
        values.pop("_external", None)  # Starlette url_for is always absolute
        scheme = values.pop("_scheme", None)
        url = self.request.url_for(endpoint, **values)
        if scheme:
            url = url.replace(scheme=scheme)
        return str(url)

    def redirect(self, location: str) -> Any:  # noqa: PLR6301
        """Build a Starlette redirect response to ``location``.

        Returns:
            A 302 ``RedirectResponse``.
        """
        return RedirectResponse(location, status_code=302)

    def current_host(self) -> str:
        """Host (netloc) of the active request.

        Returns:
            The request netloc string.
        """
        return self.request.url.netloc

    def coerce_response(self, result: Any) -> Any:  # noqa: PLR6301
        """Build a Starlette response from an ``_authorize`` return value.

        Returns:
            A Starlette response (passthrough if already one).
        """
        if isinstance(result, StarletteResponse):
            return result
        if isinstance(result, tuple):
            body, *rest = result
            status = rest[0] if rest else 200
            headers = rest[1] if len(rest) > 1 else None
            return PlainTextResponse(body, status_code=status, headers=headers)
        if isinstance(result, str):
            return PlainTextResponse(result)
        return PlainTextResponse(str(result))

    @staticmethod
    def _has_session_middleware(server) -> bool:
        return any(
            getattr(m, "cls", None) is SessionMiddleware
            for m in getattr(server, "user_middleware", [])
        )

    def setup_session(self, server, secret_key: str | None) -> None:
        """Install Starlette ``SessionMiddleware`` from ``secret_key``.

        Defers to a user-installed ``SessionMiddleware`` (opt-out/override)
        and is idempotent — never adds a second instance.
        """
        if secret_key is None:
            return
        if self._has_session_middleware(server):
            return
        server.add_middleware(SessionMiddleware, secret_key=secret_key)

    def session_configured(self, server) -> bool:
        """Whether a ``SessionMiddleware`` is installed on the server.

        Returns:
            True if session storage is available.
        """
        return self._has_session_middleware(server)

    def store_config(self, server, key: str, value: Any) -> None:  # noqa: PLR6301
        """Stash an app-scoped config value on the FastAPI ``server.state``."""
        setattr(server.state, key, value)

    def read_config(  # noqa: PLR6301
        self, server, key: str, default: Any = None
    ) -> Any:
        """Read an app-scoped config value off the FastAPI ``server.state``.

        Returns:
            The stored value, or ``default`` when unset.
        """
        return getattr(server.state, key, default)

    def register_auth_hook(self, server, needs_body, decide) -> None:
        """Register the before-request auth hook as pure-ASGI middleware.

        Pure ASGI (not ``BaseHTTPMiddleware``) so the request ContextVar set
        here is visible inside the Dash callback, which runs in the same
        task/context via the inner DashMiddleware's ``copy_context()``.
        """
        backend = self

        class _AuthMiddleware:
            def __init__(self, app) -> None:
                self.app = app

            async def __call__(self, scope, receive, send) -> None:
                if scope["type"] != "http":
                    await self.app(scope, receive, send)
                    return

                request = StarletteRequest(scope, receive)
                token = _current_request_var.set(request)
                try:
                    body = None
                    downstream_receive = receive
                    if needs_body(request.url.path):
                        # Consuming the body drains the receive stream; cache
                        # the bytes and replay them so DashMiddleware (inner)
                        # can re-parse the callback JSON.
                        raw = await request.body()

                        # Must be a coroutine to satisfy the ASGI `receive`
                        # interface, even though this replay never awaits.
                        async def downstream_receive():  # noqa: RUF029
                            return {
                                "type": "http.request",
                                "body": raw,
                                "more_body": False,
                            }

                        try:
                            body = await request.json()
                        except Exception:  # unparseable == no body
                            body = None

                    result = decide(request.url.path, body)
                    if inspect.isawaitable(result):
                        result = await result

                    if result is not None:
                        response = backend.coerce_response(result)
                        await response(scope, receive, send)
                        return

                    await self.app(scope, downstream_receive, send)
                finally:
                    _current_request_var.reset(token)

        server.add_middleware(_AuthMiddleware)


def detect_backend(server: Any) -> Backend:
    """Return the matching backend for a Flask, Quart, or FastAPI server."""
    if quart is not None:
        if isinstance(server, quart.Quart):
            return QuartBackend()
    if HAS_FASTAPI and isinstance(server, fastapi.FastAPI):
        return FastAPIBackend()
    if isinstance(server, flask.Flask):
        return FlaskBackend()

    raise NotImplementedError(
        f"No backend implemented for server type {type(server)}. "
        "If you are using a custom server, please provide a custom Backend "
        "instance to Auth(..., backend=MyBackend())."
    )


# One backend per process, matching how Dash apps are deployed.
_active_backend: Backend | None = None
_DEFAULT_BACKEND = FlaskBackend()


def set_active_backend(backend: Backend) -> None:
    """Register the backend used by request-context helpers.

    Called by Auth.__init__; group_protection functions run inside Dash
    callbacks with no auth instance in scope and look the backend up here.
    """
    global _active_backend  # noqa: PLW0603 — one backend per process, by design
    _active_backend = backend


def get_active_backend() -> Backend:
    """Return the active backend, defaulting to Flask when none is set."""
    return _active_backend if _active_backend is not None else _DEFAULT_BACKEND
