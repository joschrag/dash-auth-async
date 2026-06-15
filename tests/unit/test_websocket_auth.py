"""Unit tests for the WebSocket auth primitives."""

import contextvars
from concurrent.futures import ThreadPoolExecutor

from dash_auth_async import check_groups
from dash_auth_async.websocket_auth import _ContextCopyingExecutor, _WS_AUTH_USER

_probe: "contextvars.ContextVar[str]" = contextvars.ContextVar(
    "probe", default="DEFAULT"
)


def test_check_groups_uses_ws_contextvar_without_request_context():
    """Outside any request context, group checks read the WS-auth contextvar."""
    token = _WS_AUTH_USER.set({"email": "a.b@mail.com", "groups": ["admin"]})
    try:
        assert check_groups(groups=["admin"]) is True
        assert check_groups(groups=["viewer"]) is False
    finally:
        _WS_AUTH_USER.reset(token)


def test_check_groups_none_when_no_context_and_no_ws_user():
    """No request context and no WS user -> unauthenticated (None)."""
    assert _WS_AUTH_USER.get() is None
    assert check_groups(groups=["admin"]) is None


def test_context_copying_executor_propagates_contextvar():
    """The custom executor runs tasks in a copy of the submitter's context."""
    token = _probe.set("SET-IN-SUBMITTER")
    try:
        with _ContextCopyingExecutor(max_workers=1) as ex:
            assert ex.submit(_probe.get).result() == "SET-IN-SUBMITTER"
    finally:
        _probe.reset(token)


def test_plain_executor_does_not_propagate_contextvar():
    """Control: a plain ThreadPoolExecutor worker sees the default, proving the
    custom executor is doing real work."""
    token = _probe.set("SET-IN-SUBMITTER")
    try:
        with ThreadPoolExecutor(max_workers=1) as ex:
            assert ex.submit(_probe.get).result() == "DEFAULT"
    finally:
        _probe.reset(token)
