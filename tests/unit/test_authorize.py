"""Pure unit tests for Auth._authorize, the sans-IO auth decision core.

These run without a Flask/Quart request context, server, or browser: a
FakeBackend stands in for the framework, and _authorize is called directly
with (path, body) as specified in the pluggable-backend design spec.
"""

from types import SimpleNamespace

import pytest
from dash import Dash, Input, Output, State

from dash_auth_async.auth import Auth
from dash_auth_async.backends import Backend
from dash_auth_async.public_routes import PUBLIC_CALLBACKS

LOGIN = "login-sentinel"
CALLBACK_PATH = "/_dash-update-component"


pytestmark = pytest.mark.usefixtures("reset_active_backend")


class FakeBackend(Backend):
    """In-memory backend so the decision logic runs without a framework."""

    def __init__(self):
        self.request = SimpleNamespace(path="/")
        self.session = {}
        self.registered_hook = None

    def has_request_context(self) -> bool:
        return True

    def register_auth_hook(self, server, needs_body, decide) -> None:
        self.registered_hook = (needs_body, decide)

    def url_for(self, endpoint: str, **values) -> str:
        return f"/{endpoint}"

    def redirect(self, location: str):
        return ("redirect", location)


class StubAuth(Auth):
    def __init__(self, app, authorized=False, public_routes=None):
        self.authorized = authorized
        super().__init__(app, public_routes=public_routes, backend=FakeBackend())

    def is_authorized(self):
        return self.authorized

    def login_request(self):
        return LOGIN


def authorize(auth, path, body=None):
    # _authorize still reads self.request.path alongside its path argument;
    # keep the two consistent, as they always are in a live request.
    auth.backend.request.path = path
    return auth._authorize(path, body)


def test_public_route_allows_unauthenticated_request():
    auth = StubAuth(Dash(__name__), authorized=False, public_routes=["/home"])
    assert authorize(auth, "/home") is None


def test_base_public_routes_added_alongside_custom_ones():
    auth = StubAuth(Dash(__name__), authorized=False, public_routes=["/home"])
    assert authorize(auth, "/_dash-layout") is None


def test_private_route_unauthorized_returns_login_request():
    auth = StubAuth(Dash(__name__), authorized=False, public_routes=["/home"])
    assert authorize(auth, "/private") == LOGIN


def test_private_route_authorized_is_allowed():
    auth = StubAuth(Dash(__name__), authorized=True)
    assert authorize(auth, "/private") is None


def test_callback_with_missing_body_returns_login_request():
    auth = StubAuth(Dash(__name__), authorized=False)
    assert authorize(auth, CALLBACK_PATH, None) == LOGIN


def test_public_callback_is_allowed():
    app = Dash(__name__)
    auth = StubAuth(app, authorized=False)
    app.server.config[PUBLIC_CALLBACKS] = ["output.children"]
    body = {"output": "output.children", "inputs": []}
    assert authorize(auth, CALLBACK_PATH, body) is None


def _app_with_callbacks():
    """App with one routing callback (pathname input) and one private one."""
    app = Dash(__name__)

    @app.callback(
        Output("page", "children"),
        Input("url", "pathname"),
        State("store", "data"),
    )
    def route(pathname, data):
        return pathname

    @app.callback(
        Output("secret", "children"),
        Input("btn", "n_clicks"),
        State("q", "value"),
    )
    def secret(n_clicks, value):
        return "secret"

    return app


def _routing_body(pathname):
    return {
        "output": "page.children",
        "inputs": [{"id": "url", "property": "pathname", "value": pathname}],
        "state": [{"id": "store", "property": "data", "value": None}],
    }


def test_routing_callback_with_public_pathname_is_allowed():
    auth = StubAuth(_app_with_callbacks(), authorized=False, public_routes=["/home"])
    assert authorize(auth, CALLBACK_PATH, _routing_body("/home")) is None
    assert auth.authorize_ws(_routing_body("/home"), None) is True


def test_routing_callback_with_private_pathname_returns_login_request():
    auth = StubAuth(_app_with_callbacks(), authorized=False, public_routes=["/home"])
    assert authorize(auth, CALLBACK_PATH, _routing_body("/private")) == LOGIN
    assert auth.authorize_ws(_routing_body("/private"), None) is False


@pytest.mark.parametrize(
    "inputs, state",
    [
        # The registered n_clicks input relabelled as a pathname.
        (
            [{"id": "btn", "property": "pathname", "value": "/home"}],
            [{"id": "q", "property": "value", "value": "x"}],
        ),
        # Same, using a default public route as the pass value.
        (
            [{"id": "btn", "property": "pathname", "value": "/_dash-layout"}],
            [{"id": "q", "property": "value", "value": "x"}],
        ),
        # The state argument moved into ``inputs`` and relabelled.
        (
            [
                {"id": "btn", "property": "n_clicks", "value": 1},
                {"id": "q", "property": "pathname", "value": "/home"},
            ],
            [],
        ),
    ],
)
def test_relabelling_an_input_as_pathname_does_not_bypass_auth(inputs, state):
    """The body's ``property`` labels are client-controlled and must not decide
    whether a callback is a routing callback.

    Regression: Dash only validates the argument count, so relabelling any
    input of a private callback as ``pathname`` with a public-route value
    skipped ``is_authorized()`` entirely.
    """
    auth = StubAuth(_app_with_callbacks(), authorized=False, public_routes=["/home"])
    body = {"output": "secret.children", "inputs": inputs, "state": state}
    assert authorize(auth, CALLBACK_PATH, body) == LOGIN
    assert auth.authorize_ws(body, None) is False


def test_routing_pathname_is_read_at_the_registered_position():
    """A public value on a *different* argument must not vouch for a private
    pathname: only the argument the callback receives as pathname counts."""
    auth = StubAuth(_app_with_callbacks(), authorized=False, public_routes=["/home"])
    body = {
        "output": "page.children",
        "inputs": [
            {"id": "url", "property": "pathname", "value": "/private"},
            {"id": "store", "property": "pathname", "value": "/home"},
        ],
        "state": [],
    }
    assert authorize(auth, CALLBACK_PATH, body) == LOGIN


def test_unregistered_callback_with_public_pathname_returns_login_request():
    auth = StubAuth(_app_with_callbacks(), authorized=False, public_routes=["/home"])
    body = {
        "output": "nope.children",
        "inputs": [{"id": "url", "property": "pathname", "value": "/home"}],
    }
    assert authorize(auth, CALLBACK_PATH, body) == LOGIN


def test_private_callback_unauthorized_returns_login_request():
    auth = StubAuth(Dash(__name__), authorized=False)
    body = {"output": "output.children", "inputs": []}
    assert authorize(auth, CALLBACK_PATH, body) == LOGIN


def test_callback_body_without_inputs_key_does_not_crash():
    """A truthy body lacking the 'inputs' key must fail closed, not 500.

    Regression for indexing body["inputs"] (the WS path already used .get()).
    """
    auth = StubAuth(Dash(__name__), authorized=False)
    assert authorize(auth, CALLBACK_PATH, {"output": "x"}) == LOGIN


@pytest.mark.parametrize("body", [[1], "x", 5, {"output": "x", "inputs": 5}])
def test_callback_with_non_object_body_returns_login_request(body):
    """Valid JSON that is not the expected object must fail closed, not 500.

    Regression: a list/string/number body reached ``body.get`` and raised
    ``AttributeError``, so any unauthenticated client could trigger a 500.
    """
    auth = StubAuth(Dash(__name__), authorized=False)
    assert authorize(auth, CALLBACK_PATH, body) == LOGIN


def test_callback_path_respects_url_base_prefix():
    auth = StubAuth(
        Dash(__name__, url_base_pathname="/app/"),
        authorized=False,
    )
    assert auth._callback_path() == "/app/_dash-update-component"
    assert authorize(auth, "/app/_dash-update-component", None) == LOGIN


class _CustomServer:
    """A server type none of the built-in backends recognises."""

    def __init__(self):
        self.config = {}


class _CustomApp:
    """Minimal Dash-app double running on a custom server."""

    def __init__(self, server=None):
        self.server = server if server is not None else _CustomServer()
        self.config = {}
        self.callback_map = {}


def test_custom_backend_is_used_for_an_unrecognised_server():
    """``backend=`` exists for servers that are not Flask/Quart/FastAPI.

    Regression: the public-route helpers re-detected the backend from the
    server type on every call, so a custom backend raised
    ``NotImplementedError`` at construction and on every request.
    """
    auth = StubAuth(_CustomApp(), authorized=False, public_routes=["/home"])
    assert authorize(auth, "/home") is None
    assert authorize(auth, "/private") == LOGIN
    assert authorize(auth, CALLBACK_PATH, {"output": "x", "inputs": []}) == LOGIN


def test_basic_auth_forwards_a_custom_backend():
    from dash_auth_async import BasicAuth

    backend = FakeBackend()
    auth = BasicAuth(Dash(__name__), {"alice": "secret"}, backend=backend)
    assert auth.backend is backend


class _SlottedServer:
    """A custom server that can't be weakly referenced (``__slots__``)."""

    __slots__ = ("config",)

    def __init__(self):
        self.config = {}


def test_custom_backend_works_for_a_server_without_weakref_support():
    """Regression: ``register_backend`` keyed a ``WeakKeyDictionary`` without
    the ``TypeError`` guard ``detect_backend`` has, so ``Auth(...)`` crashed
    for exactly the custom servers ``backend=`` exists for.
    """
    auth = StubAuth(
        _CustomApp(_SlottedServer()), authorized=False, public_routes=["/home"]
    )
    assert authorize(auth, "/home") is None
    assert authorize(auth, "/private") == LOGIN
