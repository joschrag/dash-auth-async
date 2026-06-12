from dash import Dash

from dash_auth_async.backends import (
    FlaskBackend,
    QuartBackend,
    detect_backend,
    get_active_backend,
    set_active_backend,
)


def test_detect_backend_flask():
    app = Dash(__name__)
    assert isinstance(detect_backend(app.server), FlaskBackend)


def test_detect_backend_quart():
    app = Dash(__name__, backend="quart")
    assert isinstance(detect_backend(app.server), QuartBackend)


def test_active_backend_defaults_to_flask():
    assert isinstance(get_active_backend(), FlaskBackend)


def test_active_backend_roundtrip():
    backend = QuartBackend()
    set_active_backend(backend)
    assert get_active_backend() is backend
