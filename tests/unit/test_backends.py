from dash import Dash

from dash_auth_async.backends import (
    FlaskBackend,
    detect_backend,
    get_active_backend,
)


def test_detect_backend_flask():
    app = Dash(__name__)
    assert isinstance(detect_backend(app.server), FlaskBackend)


def test_active_backend_defaults_to_flask():
    assert isinstance(get_active_backend(), FlaskBackend)


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
