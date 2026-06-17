import pytest

pytest.importorskip("fastapi", reason="FastAPI extra dependencies are not installed")

from starlette.requests import Request

from dash_auth_async import check_groups, list_groups
from dash_auth_async.backends import (
    FastAPIBackend,
    _current_request_var,
    set_active_backend,
)


def _request_with_session(session):
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [],
        "query_string": b"",
    }
    if session is not None:
        scope["session"] = session
    return Request(scope)


def test_gp_list_groups_fastapi():
    set_active_backend(FastAPIBackend())
    req = _request_with_session(
        {"user": {"email": "a.b@mail.com", "groups": ["default"]}}
    )
    token = _current_request_var.set(req)
    try:
        assert list_groups() == ["default"]
        assert check_groups(["default"]) is True
        assert check_groups(["other"]) is False
    finally:
        _current_request_var.reset(token)


def test_gp_no_session_returns_none():
    set_active_backend(FastAPIBackend())
    req = _request_with_session(None)  # no SessionMiddleware -> session raises
    token = _current_request_var.set(req)
    try:
        assert list_groups() is None
        assert check_groups(["default"]) is None
    finally:
        _current_request_var.reset(token)
