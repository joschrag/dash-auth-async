import pytest
from dash import Dash

from dash_auth_async import backends
from dash_auth_async.backends import (
    FlaskBackend,
    detect_backend,
    get_active_backend,
    set_active_backend,
)

pytestmark = pytest.mark.usefixtures("reset_active_backend")


def test_detect_backend_flask():
    app = Dash(__name__)
    assert isinstance(detect_backend(app.server), FlaskBackend)


def test_active_backend_defaults_to_flask():
    assert isinstance(get_active_backend(), FlaskBackend)


def test_set_active_backend_overrides_default():
    sentinel = FlaskBackend()
    set_active_backend(sentinel)
    # The process-global helper returns exactly what Auth.__init__ registered,
    # not a freshly detected backend — this is the cache public_routes reads.
    assert get_active_backend() is sentinel


def test_default_backend_is_not_constructed_eagerly_at_import():
    # B2: the Flask fallback is built lazily inside get_active_backend(), not
    # as a module-level _DEFAULT_BACKEND at import, so Flask isn't cemented as
    # the default at module load in a non-Flask process.
    assert not hasattr(backends, "_DEFAULT_BACKEND")


def test_flask_backend_url_for_and_redirect():
    app = Dash(__name__)
    server = app.server

    @server.route("/target")
    def target():
        return "ok"

    backend = FlaskBackend()
    with server.test_request_context("/"):
        assert backend.url_for("target") == "/target"
        response = backend.redirect("/target")
        assert response.status_code == 302
        assert response.headers["Location"] == "/target"


def test_flask_backend_new_method_defaults():
    import flask

    from dash_auth_async.backends import FlaskBackend

    backend = FlaskBackend()

    # coerce_response is pass-through on Flask
    sentinel = ("body", 401, {"X": "y"})
    assert backend.coerce_response(sentinel) is sentinel

    # setup_session sets secret_key; session_configured reflects it
    server = flask.Flask(__name__)
    assert backend.session_configured(server) is False
    backend.setup_session(server, "Test!")
    assert server.secret_key == "Test!"
    assert backend.session_configured(server) is True

    # make_oauth returns a flask_client OAuth bound to the server
    from authlib.integrations.flask_client import OAuth as FlaskOAuth

    oauth = backend.make_oauth(server)
    assert isinstance(oauth, FlaskOAuth)


def test_session_get_is_none_off_request_and_without_secret_key():
    """``session_get`` never raises: None off-request and with no session."""
    app = Dash(__name__)
    backend = FlaskBackend()
    assert backend.session_get("user") is None  # no request context
    with app.server.test_request_context("/"):  # no secret_key -> no session
        assert backend.session_get("user") is None
    app.server.secret_key = "k"
    with app.server.test_request_context("/"):
        backend.session["user"] = {"email": "a"}
        assert backend.session_get("user") == {"email": "a"}


def test_public_api_exports_base_classes_and_backends():
    """``Auth``, ``Backend`` and the built-in backends import from the top level.

    ``Auth`` matches upstream ``dash_auth``; ``Backend`` is what the README tells
    users to subclass for custom servers.
    """
    import dash_auth_async
    from dash_auth_async import auth, public_routes

    assert dash_auth_async.Auth is auth.Auth
    assert dash_auth_async.Backend is backends.Backend
    assert dash_auth_async.FlaskBackend is backends.FlaskBackend
    assert dash_auth_async.QuartBackend is backends.QuartBackend
    assert dash_auth_async.FastAPIBackend is backends.FastAPIBackend
    assert dash_auth_async.get_url_base is public_routes.get_url_base
    assert all(hasattr(dash_auth_async, name) for name in dash_auth_async.__all__)


def test_quart_backend_without_quart_raises(monkeypatch):
    monkeypatch.setattr(backends, "HAS_QUART", False)
    with pytest.raises(ImportError, match="pip install quart"):
        backends.QuartBackend()
