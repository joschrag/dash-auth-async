from abc import ABC, abstractmethod
from typing import Any, Callable, MutableMapping, Optional

import flask

try:
    import quart

    HAS_QUART = True
except ImportError:
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
        decide: Callable[[str, Optional[dict]], Any],
    ) -> None:
        """Register a before-request auth hook on the server.

        :param server: the Flask or Quart server instance
        :param needs_body: whether the JSON body must be parsed for this
            request path (evaluated per request)
        :param decide: pure decision function receiving
            (path, parsed_body_or_None); returns None to allow the request
            or a response value to short-circuit it
        """


class FlaskBackend(Backend):
    # Properties, not class attributes: ABCMeta probes every namespace
    # value for __isabstractmethod__ at class creation, which unwraps
    # the context-local proxies outside any request and raises.
    @property
    def request(self) -> Any:
        return flask.request

    @property
    def session(self) -> MutableMapping:
        return flask.session

    def has_request_context(self) -> bool:
        return flask.has_request_context()

    def register_auth_hook(self, server, needs_body, decide) -> None:
        @server.before_request
        def before_request_auth():
            body = (
                flask.request.get_json(silent=True)
                if needs_body(flask.request.path)
                else None
            )
            return decide(flask.request.path, body)


class QuartBackend(Backend):
    def __init__(self):
        if not HAS_QUART:
            raise ImportError(
                "Quart support requires the [quart] extra dependency. "
                "Install it via: pip install dash-auth-async[quart]"
            )

    @property
    def request(self) -> Any:
        return quart.request

    @property
    def session(self) -> MutableMapping:
        return quart.session

    def has_request_context(self) -> bool:
        return quart.has_request_context()

    def register_auth_hook(self, server, needs_body, decide) -> None:
        @server.before_request
        async def before_request_auth():
            body = (
                await quart.request.get_json(silent=True)
                if needs_body(quart.request.path)
                else None
            )
            return decide(quart.request.path, body)


def detect_backend(server) -> Backend:
    """Return the matching backend for a Flask or Quart server."""
    if HAS_QUART and isinstance(server, quart.Quart):
        return QuartBackend()
    return FlaskBackend()


# One backend per process, matching how Dash apps are deployed.
_active_backend: Optional[Backend] = None
_DEFAULT_BACKEND = FlaskBackend()


def set_active_backend(backend: Backend) -> None:
    """Register the backend used by request-context helpers.

    Called by Auth.__init__; group_protection functions run inside Dash
    callbacks with no auth instance in scope and look the backend up here.
    """
    global _active_backend
    _active_backend = backend


def get_active_backend() -> Backend:
    """Return the active backend, defaulting to Flask when none is set."""
    return _active_backend if _active_backend is not None else _DEFAULT_BACKEND
