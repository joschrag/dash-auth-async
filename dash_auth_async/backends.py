"""Framework adapters isolating Flask/Quart-specific request and session I/O."""

from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from collections.abc import Callable, MutableMapping
from typing import Any

import flask

try:
    import quart

    HAS_QUART = True
except ImportError:
    quart: Any = None
    HAS_QUART = False


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


def detect_backend(server: Any) -> Backend:
    """Return the matching backend for a Flask or Quart server."""
    if quart is not None:
        if isinstance(server, quart.Quart):
            return QuartBackend()
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
