"""Unit tests for the WebSocket auth primitives."""

from dash_auth_async.websocket_auth import _WS_AUTH_USER
from dash_auth_async import check_groups


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
