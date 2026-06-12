import pytest
from dash import Dash

from dash_auth_async.backends import (
    QuartBackend,
    detect_backend,
    get_active_backend,
    set_active_backend,
)

pytest.importorskip("quart", reason="Quart extra dependencies are not installed")


def test_detect_backend_quart():
    app = Dash(__name__, backend="quart")
    assert isinstance(detect_backend(app.server), QuartBackend)


def test_active_backend_roundtrip():
    backend = QuartBackend()
    set_active_backend(backend)
    assert get_active_backend() is backend
