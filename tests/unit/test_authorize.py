"""Pure unit tests for Auth._authorize, the sans-IO auth decision core.

These run without a Flask/Quart request context, server, or browser: a
FakeBackend stands in for the framework, and _authorize is called directly
with (path, body) as specified in the pluggable-backend design spec.
"""

from types import SimpleNamespace

from dash import Dash

from dash_auth_async.auth import Auth
from dash_auth_async.backends import Backend
from dash_auth_async.public_routes import PUBLIC_CALLBACKS

LOGIN = "login-sentinel"
CALLBACK_PATH = "/_dash-update-component"


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


def test_routing_callback_with_public_pathname_is_allowed():
    auth = StubAuth(Dash(__name__), authorized=False, public_routes=["/home"])
    body = {
        "output": "page.children",
        "inputs": [{"property": "pathname", "value": "/home"}],
    }
    assert authorize(auth, CALLBACK_PATH, body) is None


def test_routing_callback_with_private_pathname_returns_login_request():
    auth = StubAuth(Dash(__name__), authorized=False, public_routes=["/home"])
    body = {
        "output": "page.children",
        "inputs": [{"property": "pathname", "value": "/private"}],
    }
    assert authorize(auth, CALLBACK_PATH, body) == LOGIN


def test_private_callback_unauthorized_returns_login_request():
    auth = StubAuth(Dash(__name__), authorized=False)
    body = {"output": "output.children", "inputs": []}
    assert authorize(auth, CALLBACK_PATH, body) == LOGIN


def test_callback_path_respects_url_base_prefix():
    auth = StubAuth(
        Dash(__name__, url_base_pathname="/app/"),
        authorized=False,
    )
    assert auth._callback_path() == "/app/_dash-update-component"
    assert authorize(auth, "/app/_dash-update-component", None) == LOGIN
