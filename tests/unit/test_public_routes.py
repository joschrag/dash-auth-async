"""Unit tests for the public-route/callback registration helpers."""

import pytest
from dash import Dash, Input, Output

from dash_auth_async import backends
from dash_auth_async.public_routes import (
    add_public_routes,
    get_public_callbacks,
    get_public_routes,
    public_callback,
)

pytestmark = pytest.mark.usefixtures("reset_active_backend")


def _make_identical_handler():
    """Return a handler whose source text is byte-identical across calls.

    Two of these collide under source-text matching, the exact case that made
    ``public_callback`` whitelist the wrong id (or fail to whitelist at all).
    """

    def handler(value):
        return value

    return handler


def test_public_callback_distinguishes_identical_source_callbacks():
    """Two public callbacks with identical source must each get their own id.

    Regression for the source-text matching that resolved both to the first
    match. The id is now the new key Dash adds to its callback map, so the two
    are distinguished by their (distinct) outputs.
    """
    app = Dash(__name__)
    add_public_routes(app, [])  # initialise the public-callbacks store

    public_callback(Output("a", "children"), Input("x", "value"))(
        _make_identical_handler()
    )
    public_callback(Output("b", "children"), Input("y", "value"))(
        _make_identical_handler()
    )

    ids = get_public_callbacks(app)
    assert "a.children" in ids
    assert "b.children" in ids


def test_public_callback_does_not_crash_on_lambda():
    """A lambda (or any callback whose source can't be read) must not raise.

    ``inspect.getsource`` blew up here; the new id resolution never reads source.
    """
    app = Dash(__name__)
    add_public_routes(app, [])

    public_callback(Output("c", "children"), Input("z", "value"))(lambda value: value)

    assert "c.children" in get_public_callbacks(app)


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
