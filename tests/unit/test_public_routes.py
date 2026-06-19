"""Unit tests for the public-route/callback registration helpers."""

import pytest
from dash import Dash

from dash_auth_async import backends
from dash_auth_async.public_routes import (
    add_public_routes,
    get_public_callbacks,
    get_public_routes,
)


def test_public_helpers_resolve_backend_from_app_server_not_global_fallback():
    """The public-route helpers must resolve the backend from ``app.server``,
    not the process-global ``get_active_backend()`` (which falls back to
    ``FlaskBackend``). On a FastAPI app that fallback's ``store_config`` would
    write to the nonexistent ``server.config``; ``detect_backend(app.server)``
    routes through ``server.state`` instead.

    Regression guard for the FastAPI public-route registration path: with no
    ``Auth`` having set the active backend, the global is the Flask fallback,
    so a helper that trusted it would ``AttributeError`` here.
    """
    pytest.importorskip(
        "fastapi", reason="FastAPI extra dependencies are not installed"
    )

    # Leave the active backend unset -> get_active_backend() is the Flask
    # fallback, the exact condition that exposed the bug.
    backends._active_backend = None

    app = Dash(__name__, backend="fastapi")

    # Would raise AttributeError (no server.config) under the Flask fallback.
    add_public_routes(app, ["/login"])

    # Stored on (and read back from) the FastAPI server.state, not server.config.
    assert get_public_routes(app) is app.server.state.PUBLIC_ROUTES
    assert any(
        rule.rule == "/login" for rule in get_public_routes(app).map.iter_rules()
    )

    # The callbacks reader returns its default through the same backend path.
    assert get_public_callbacks(app) == []
