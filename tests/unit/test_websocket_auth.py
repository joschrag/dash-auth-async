"""Unit tests for the WebSocket auth primitives."""

import contextvars
from concurrent.futures import ThreadPoolExecutor

import pytest
from dash.exceptions import PreventUpdate

from dash_auth_async import check_groups
from dash_auth_async.group_protection import (
    _current_user,
    _prevent_unauthorised,
)
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


def test_current_user_reads_ws_contextvar_without_request_context():
    """Off-request, the caller is resolved from the WS contextvar, not session."""
    assert _current_user() is None
    user = {"email": "a.b@mail.com", "groups": ["viewer"]}
    token = _WS_AUTH_USER.set(user)
    try:
        assert _current_user() == user
    finally:
        _WS_AUTH_USER.reset(token)


def test_default_missing_permissions_fallback_fails_closed_over_ws():
    """The default ``missing_permissions_output`` must gate gracefully over WS.

    On the WebSocket worker path there is no request context, so the old
    fallback's ``backend.session["user"]["email"]`` raised ``RuntimeError``
    instead of the contractual ``PreventUpdate`` -- failing closed but throwing
    an unhandled error. It must resolve the user from the WS contextvar instead.
    """
    token = _WS_AUTH_USER.set({"email": "a.b@mail.com", "groups": ["viewer"]})
    try:
        with pytest.raises(PreventUpdate):
            _prevent_unauthorised("my_callback")
    finally:
        _WS_AUTH_USER.reset(token)


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


def _build_auth_app():
    pytest.importorskip("quart", reason="Quart extra dependencies are not installed")
    from dash import Dash, Input, Output, html
    from dash_auth_async import BasicAuth, public_callback

    app = Dash(__name__, backend="quart")
    app.layout = html.Div(
        [html.Div(id="priv"), html.Div(id="pub"), html.Button("b", id="pub-in")]
    )

    @public_callback(Output("pub", "children"), Input("pub-in", "n_clicks"))
    async def pub_cb(n):
        return n

    auth = BasicAuth(
        app, {"hello": "world"}, user_groups={"hello": ["admin"]}, secret_key="Test!"
    )
    return app, auth


def test_authorize_ws_allows_authenticated_user_for_private_callback():
    _app, auth = _build_auth_app()
    payload = {"output": "priv.children", "inputs": []}
    assert auth.authorize_ws(payload, {"email": "x", "groups": []}) is True


def test_authorize_ws_denies_unauthenticated_user_for_private_callback():
    _app, auth = _build_auth_app()
    payload = {"output": "priv.children", "inputs": []}
    assert auth.authorize_ws(payload, None) is False


def test_authorize_ws_allows_public_callback_even_unauthenticated():
    _app, auth = _build_auth_app()
    payload = {"output": "pub.children", "inputs": []}
    assert auth.authorize_ws(payload, None) is True


# --------------------------------------------------------------------------- #
# Multi-app hook resolution: the process-global websocket_message hook must
# dispatch each message to the Auth owning the connection's current_app.
# --------------------------------------------------------------------------- #
class _Server:
    """Weak-referenceable stand-in for an app.server (the registry key)."""


class _RecordingAuth:
    """Auth double that records the calls the hook routes to it."""

    def __init__(self) -> None:
        self.calls: list = []

    def authorize_ws(self, payload, user) -> bool:
        self.calls.append((payload, user))
        return True


def test_ws_hook_resolves_auth_for_the_current_app(monkeypatch):
    """With two dash-auth-async apps in the process, the hook consults only the
    Auth registered for ``quart.current_app`` -- not some other app's Auth."""
    quart = pytest.importorskip("quart")
    from dash_auth_async.websocket_auth import (
        _AUTH_BY_SERVER,
        _WS_AUTH_USER,
        _ws_message_hook,
    )

    server_a, server_b = _Server(), _Server()
    auth_a, auth_b = _RecordingAuth(), _RecordingAuth()
    _AUTH_BY_SERVER[server_a] = auth_a
    _AUTH_BY_SERVER[server_b] = auth_b

    # The connection's current_app resolves to app B's server.
    class _CurrentApp:
        def _get_current_object(self):
            return server_b

    user = {"email": "b@mail.com", "groups": ["admin"]}
    monkeypatch.setattr(quart, "current_app", _CurrentApp(), raising=False)
    monkeypatch.setattr(quart, "session", {"user": user}, raising=False)
    token = _WS_AUTH_USER.set(None)
    try:
        message = {"type": "callback_request", "payload": {"output": "x.children"}}
        result = _ws_message_hook(object(), message)

        assert result is True
        # Only app B's Auth was consulted, with app B's session user.
        assert auth_b.calls == [({"output": "x.children"}, user)]
        assert auth_a.calls == []
        # The resolved user was stashed for the worker.
        assert _WS_AUTH_USER.get() == user
    finally:
        _WS_AUTH_USER.reset(token)
        del _AUTH_BY_SERVER[server_a]
        del _AUTH_BY_SERVER[server_b]
