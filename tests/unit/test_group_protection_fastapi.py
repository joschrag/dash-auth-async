import asyncio
import inspect

import pytest

pytest.importorskip("fastapi", reason="FastAPI extra dependencies are not installed")

from starlette.requests import Request

from dash_auth_async import check_groups, list_groups, protected
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


def test_gp_async_protected_unauthenticated_without_session_user():
    """An async ``protected`` wrapper with no logged-in user (empty session)
    short-circuits to ``unauthenticated_output`` over the FastAPI backend, while
    staying a coroutine so Dash keeps it on the async dispatch path.
    """
    set_active_backend(FastAPIBackend())
    req = _request_with_session({})  # session available, but no "user"
    token = _current_request_var.set(req)
    try:

        async def func():
            return "success"

        wrapped = protected(
            unauthenticated_output="unauthenticated",
            missing_permissions_output="forbidden",
            groups=["admin"],
        )(func)

        assert inspect.iscoroutinefunction(wrapped)
        assert asyncio.run(wrapped()) == "unauthenticated"
    finally:
        _current_request_var.reset(token)
