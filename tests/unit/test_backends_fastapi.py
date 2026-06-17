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


def _build_app_with_auth(decide, needs_body):
    """A FastAPI app whose only middleware is the auth hook, plus an echo
    route that proves the body survives middleware body-consumption."""
    from fastapi import FastAPI

    app = FastAPI()
    backend = FastAPIBackend()

    @app.post("/_dash-update-component")
    async def echo(request: Request):
        body = await request.json()
        return {"seen": body, "had_context": backend.has_request_context()}

    @app.get("/open")
    async def open_route():
        return {"ok": True}

    backend.register_auth_hook(app, needs_body, decide)
    return app


def test_auth_hook_allows_when_decide_returns_none():
    from fastapi.testclient import TestClient

    calls = []

    def decide(path, body):
        calls.append((path, body))

    app = _build_app_with_auth(
        decide, needs_body=lambda p: p == "/_dash-update-component"
    )
    client = TestClient(app)

    r = client.post("/_dash-update-component", json={"output": "x", "inputs": []})
    assert r.status_code == 200
    # Body was replayed: the downstream route still parsed it.
    assert r.json()["seen"] == {"output": "x", "inputs": []}
    assert r.json()["had_context"] is True
    # decide saw the parsed body for the callback route.
    assert calls == [("/_dash-update-component", {"output": "x", "inputs": []})]


def test_auth_hook_short_circuits_with_tuple():
    from fastapi.testclient import TestClient

    def decide(path, body):
        return ("Login Required", 401, {"WWW-Authenticate": 'Basic realm="x"'})

    app = _build_app_with_auth(decide, needs_body=lambda p: False)
    client = TestClient(app)

    r = client.get("/open")
    assert r.status_code == 401
    assert r.headers["WWW-Authenticate"] == 'Basic realm="x"'
    assert r.text == "Login Required"


def test_auth_hook_awaits_coroutine_results():
    from fastapi.testclient import TestClient
    from starlette.responses import PlainTextResponse

    async def decide(path, body):
        return PlainTextResponse("async-block", status_code=403)

    app = _build_app_with_auth(decide, needs_body=lambda p: False)
    client = TestClient(app)

    r = client.get("/open")
    assert r.status_code == 403
    assert r.text == "async-block"
