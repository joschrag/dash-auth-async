import pytest
from dash import Dash

from dash_auth_async.backends import (
    QuartBackend,
    detect_backend,
    get_active_backend,
    set_active_backend,
)

pytest.importorskip("quart", reason="Quart extra dependencies are not installed")


pytestmark = pytest.mark.usefixtures("reset_active_backend")


def test_detect_backend_quart():
    app = Dash(__name__, backend="quart")
    assert isinstance(detect_backend(app.server), QuartBackend)


def test_active_backend_roundtrip():
    backend = QuartBackend()
    set_active_backend(backend)
    assert get_active_backend() is backend


def test_quart_backend_url_for_and_redirect():
    import asyncio

    from quart import Quart

    app = Quart(__name__)

    @app.route("/target")
    async def target():
        return "ok"

    backend = QuartBackend()

    async def run():
        # quart annotates __aexit__ args without Optional, violating the
        # protocol on clean exit; works at runtime.
        async with app.test_request_context("/", method="GET"):  # ty: ignore[invalid-context-manager]
            assert backend.url_for("target") == "/target"
            response = backend.redirect("/target")
            assert response.status_code == 302
            assert response.headers["Location"] == "/target"

    asyncio.run(run())
