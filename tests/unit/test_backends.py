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
