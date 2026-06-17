import pytest
from dash import Dash

pytest.importorskip("fastapi", reason="FastAPI extra dependencies are not installed")

from starlette.requests import Request

from dash_auth_async.backends import (
    FastAPIBackend,
    _current_request_var,
    detect_backend,
    get_active_backend,
    set_active_backend,
)


def _bare_request(path="/", session=None):
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": [],
        "query_string": b"",
    }
    if session is not None:
        scope["session"] = session
    return Request(scope)


def test_detect_backend_fastapi():
    app = Dash(__name__, backend="fastapi")
    assert isinstance(detect_backend(app.server), FastAPIBackend)


def test_active_backend_roundtrip():
    backend = FastAPIBackend()
    set_active_backend(backend)
    assert get_active_backend() is backend


def test_contextvar_set_reset_and_request_context():
    backend = FastAPIBackend()
    assert backend.has_request_context() is False

    req = _bare_request()
    token = _current_request_var.set(req)
    try:
        assert backend.has_request_context() is True
        assert backend.request is req
    finally:
        _current_request_var.reset(token)
    assert backend.has_request_context() is False


def test_session_without_middleware_raises_runtimeerror():
    backend = FastAPIBackend()
    req = _bare_request()  # no "session" in scope
    token = _current_request_var.set(req)
    try:
        with pytest.raises(RuntimeError):
            _ = backend.session
    finally:
        _current_request_var.reset(token)


def test_session_present_returns_mapping():
    backend = FastAPIBackend()
    req = _bare_request(session={"user": {"email": "a.b@mail.com"}})
    token = _current_request_var.set(req)
    try:
        assert backend.session["user"]["email"] == "a.b@mail.com"
    finally:
        _current_request_var.reset(token)


def test_coerce_response_tuple_str_and_response():
    from starlette.responses import Response as StarletteResponse

    backend = FastAPIBackend()

    resp = backend.coerce_response(
        ("Login Required", 401, {"WWW-Authenticate": 'Basic realm="x"'})
    )
    assert resp.status_code == 401
    assert resp.headers["WWW-Authenticate"] == 'Basic realm="x"'
    assert resp.body == b"Login Required"

    resp2 = backend.coerce_response("hello")
    assert resp2.status_code == 200
    assert resp2.body == b"hello"

    passthrough = StarletteResponse(content="x", status_code=204)
    assert backend.coerce_response(passthrough) is passthrough


def test_fastapi_backend_url_for_and_redirect():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    backend = FastAPIBackend()

    @app.get("/target", name="target")
    async def target():
        return {"ok": True}

    @app.get("/probe")
    async def probe(request: Request):
        token = _current_request_var.set(request)
        try:
            return {
                "url": backend.url_for("target"),
                "https_url": backend.url_for("target", _external=True, _scheme="https"),
                "redirect_loc": backend.redirect("/target").headers["location"],
                "host": backend.current_host(),
            }
        finally:
            _current_request_var.reset(token)

    client = TestClient(app)
    data = client.get("/probe").json()
    assert data["url"].endswith("/target")
    assert data["https_url"].startswith("https://")
    assert data["redirect_loc"] == "/target"
    assert data["host"]  # non-empty netloc
