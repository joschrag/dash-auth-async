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
