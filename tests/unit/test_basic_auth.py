"""Unit tests for BasicAuth — Issue 1 (S2 malformed headers, C1 init order).

These run without a browser or live server. S2 drives the real header-parsing
path inside a Flask ``test_request_context`` (FlaskBackend.request *is*
flask.request, so no mocking is needed). C1 injects a recording backend via
``detect_backend`` to observe construction order.
"""

from types import SimpleNamespace

import pytest
from dash import Dash

from dash_auth_async.backends import Backend
from dash_auth_async.basic_auth import BasicAuth

VALID_USERS = {"alice": "secret"}


def _basic_auth_app(**kwargs):
    """A Dash app with BasicAuth on the real Flask backend."""
    app = Dash(__name__)
    auth = BasicAuth(app, VALID_USERS, secret_key="test-secret", **kwargs)
    return app, auth


# --- S2: malformed Authorization headers must fail auth, never raise (500) ---

MALFORMED_HEADERS = [
    pytest.param("Bearer xyz", id="non-basic-scheme"),
    pytest.param("Basic !!!notbase64!!!", id="non-base64"),
    pytest.param("Basic bm9jb2xvbg==", id="no-colon"),  # b64('nocolon')
    pytest.param("Basic //4=", id="non-utf8"),  # b64(b'\xff\xfe')
]


@pytest.mark.parametrize("header", MALFORMED_HEADERS)
def test_malformed_authorization_header_is_unauthorized(header):
    """is_authorized() returns False (not raises) for any malformed header."""
    app, auth = _basic_auth_app()
    with app.server.test_request_context(headers={"Authorization": header}):
        assert auth.is_authorized() is False


@pytest.mark.parametrize("header", MALFORMED_HEADERS)
def test_malformed_authorization_header_returns_401_not_500(header):
    """The decision core returns the 401 login response, not a 500 traceback."""
    app, auth = _basic_auth_app()
    with app.server.test_request_context(
        path="/private", headers={"Authorization": header}
    ):
        result = auth._authorize("/private", None)
    # login_request() is ("Login Required", 401, {...})
    assert result[1] == 401


# --- Control: the well-formed paths still behave correctly ---


def test_valid_credentials_are_authorized():
    import base64

    app, auth = _basic_auth_app()
    token = base64.b64encode(b"alice:secret").decode()
    with app.server.test_request_context(headers={"Authorization": f"Basic {token}"}):
        assert auth.is_authorized() is True


def test_wrong_password_is_unauthorized():
    import base64

    app, auth = _basic_auth_app()
    token = base64.b64encode(b"alice:wrong").decode()
    with app.server.test_request_context(headers={"Authorization": f"Basic {token}"}):
        assert auth.is_authorized() is False


def test_missing_header_is_unauthorized():
    app, auth = _basic_auth_app()
    with app.server.test_request_context():
        assert auth.is_authorized() is False


# --- C1: __init__ must set auth state / validate args before wiring hooks ---


class RecordingBackend(Backend):
    """Captures instance state at the moment the auth hook is registered."""

    def __init__(self):
        self.request = SimpleNamespace(path="/", headers={})
        self.session = {}
        self.hook_registered = False
        self.attrs_at_registration = set()

    def has_request_context(self) -> bool:
        return True

    def register_auth_hook(self, server, needs_body, decide) -> None:
        self.hook_registered = True
        # decide is the bound Auth._authorize; __self__ is the instance
        # under construction.
        self.attrs_at_registration = set(vars(decide.__self__))

    def url_for(self, endpoint: str, **values) -> str:
        return f"/{endpoint}"

    def redirect(self, location: str):
        return ("redirect", location)


def test_auth_state_exists_when_hook_is_registered(monkeypatch):
    """By the time _protect() registers the hook, _users must already be set —
    otherwise a request arriving mid-construction hits is_authorized() against a
    half-initialised instance and raises AttributeError.
    """
    backend = RecordingBackend()
    monkeypatch.setattr("dash_auth_async.auth.detect_backend", lambda server: backend)
    BasicAuth(Dash(__name__), VALID_USERS)
    assert "_users" in backend.attrs_at_registration


def test_invalid_config_rejected_before_wiring_hooks(monkeypatch):
    """Passing both username list and auth_func must raise before any hook or
    executor wiring mutates server state.
    """
    backend = RecordingBackend()
    monkeypatch.setattr("dash_auth_async.auth.detect_backend", lambda server: backend)
    with pytest.raises(ValueError):
        BasicAuth(Dash(__name__), VALID_USERS, auth_func=lambda u, p: True)
    assert backend.hook_registered is False
