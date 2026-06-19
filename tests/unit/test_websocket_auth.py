"""Unit tests for the WebSocket auth primitives."""

import asyncio
import contextvars
from concurrent.futures import ThreadPoolExecutor

import pytest
from dash.exceptions import PreventUpdate

from dash_auth_async import check_groups
from dash_auth_async.group_protection import (
    _current_user,
    _prevent_unauthorised,
)
from dash_auth_async.websocket_auth import _WS_AUTH_USER, _ContextCopyingExecutor

pytestmark = pytest.mark.usefixtures("reset_active_backend")

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
    custom executor is doing real work.
    """
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


class _DashAppStub:
    """Minimal Dash-app double exposing the idempotent ``_setup_server`` the hook
    calls to migrate ``callback_map`` lazily on the first WS ``callback_request``.
    """

    def __init__(self) -> None:
        self.setup_calls = 0

    def _setup_server(self) -> None:
        self.setup_calls += 1


class _RecordingAuth:
    """Auth double that records the calls the hook routes to it."""

    def __init__(self) -> None:
        self.calls: list = []
        self.app = _DashAppStub()

    def authorize_ws(self, payload, user) -> bool:
        self.calls.append((payload, user))
        return True


# --------------------------------------------------------------------------- #
# Connection registry: the websocket_connect hook tracks sockets so a later
# login can retire the browser's stale anonymous one. It must not accumulate --
# authenticated sockets are never retired (so never tracked), and a browser's
# reconnects (one SharedWorker socket per browser) must not pile up.
# --------------------------------------------------------------------------- #
class _IdentityBackend:
    """Backend double whose ``ws_identity`` returns a fixed (server, user)."""

    def __init__(self, user) -> None:
        self._user = user

    def ws_identity(self, _ws):
        return object(), self._user


class _FakeWS:
    """Minimal socket double exposing the cookies and an awaitable close."""

    def __init__(self, client_id) -> None:
        self.cookies = {"dac_client": client_id} if client_id else {}
        self.close_code = None

    async def close(self, code=None) -> None:
        self.close_code = code


def _tracked_count(client_id) -> int:
    """Sockets tracked for ``client_id``, agnostic to the registry's shape."""
    from dash_auth_async.websocket_auth import _WS_BY_CLIENT

    entry = _WS_BY_CLIENT.get(client_id)
    if entry is None:
        return 0
    return len(entry) if isinstance(entry, (set, list, dict)) else 1


def _run_connect_hook(ws) -> None:
    from dash_auth_async.websocket_auth import _ws_connect_hook

    async def _run():
        _ws_connect_hook(ws)

    asyncio.run(_run())


def _use_backend(monkeypatch, user) -> None:
    """Point the connect hook at a backend double whose identity returns ``user``."""
    monkeypatch.setattr(
        "dash_auth_async.websocket_auth.get_active_backend",
        lambda: _IdentityBackend(user),
    )


def test_authenticated_handshake_is_not_tracked(monkeypatch):
    """A socket that handshakes already authenticated is never retired, so the
    registry must not hold it (else authenticated sockets leak unboundedly).
    """
    from dash_auth_async.websocket_auth import _WS_BY_CLIENT

    _WS_BY_CLIENT.clear()
    _use_backend(monkeypatch, {"email": "a@b.c", "groups": []})

    _run_connect_hook(_FakeWS("client-1"))

    assert _tracked_count("client-1") == 0


def test_reconnect_does_not_accumulate_entries(monkeypatch):
    """A browser has one SharedWorker socket; a reconnect replaces the prior
    anonymous entry rather than stacking, so tracking stays at one per browser.
    """
    from dash_auth_async.websocket_auth import _WS_BY_CLIENT

    _WS_BY_CLIENT.clear()
    _use_backend(monkeypatch, None)  # anonymous handshakes

    _run_connect_hook(_FakeWS("client-2"))
    _run_connect_hook(_FakeWS("client-2"))

    assert _tracked_count("client-2") == 1


def test_ws_hook_resolves_auth_for_the_current_app(monkeypatch):
    """With two dash-auth-async apps in the process, the hook consults only the
    Auth registered for ``quart.current_app`` -- not some other app's Auth.
    """
    quart = pytest.importorskip("quart")
    from dash_auth_async.backends import QuartBackend, set_active_backend
    from dash_auth_async.websocket_auth import (
        _AUTH_BY_SERVER,
        _WS_AUTH_USER,
        _ws_message_hook,
    )

    # The hook resolves identity via the active backend; this is the Quart path
    # (ws_identity reads the quart.current_app/quart.session monkeypatched below).
    # The reset_active_backend fixture clears it after the test.
    set_active_backend(QuartBackend())

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
        # The hook migrated only app B's callback_map (lazy, idempotent), and
        # never touched app A's.
        assert auth_b.app.setup_calls == 1
        assert auth_a.app.setup_calls == 0
        # The resolved user was stashed for the worker.
        assert _WS_AUTH_USER.get() == user
    finally:
        _WS_AUTH_USER.reset(token)
        del _AUTH_BY_SERVER[server_a]
        del _AUTH_BY_SERVER[server_b]
