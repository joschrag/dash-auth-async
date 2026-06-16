"""Security: the websocket callback endpoint must not bypass authentication.

Drives the raw socket with websocket-client (no browser) and asserts an
unauthenticated client cannot invoke a private callback, while a public_callback
still streams unauthenticated.
"""

import json

import pytest
from dash import Dash, Input, Output, callback, html

from dash_auth_async import BasicAuth, protected_callback, public_callback

# Guard the optional, non-extra test deps *before* importing them. CI test jobs
# install the package extras (oidc/fastapi/quart) but not the `dev` group, so
# websocket-client is absent there -- a bare top-level `import websocket` would
# crash collection instead of skipping. quart is checked first so the non-async
# matrix jobs skip cleanly without needing the socket client at all.
pytest.importorskip("quart", reason="Quart extra dependencies are not installed")
requests = pytest.importorskip("requests", reason="requests is not installed")
websocket = pytest.importorskip(  # websocket-client (synchronous)
    "websocket",
    reason="websocket-client (the 'websocket' module) is not installed",
)


def _build_app() -> Dash:
    app = Dash(__name__, backend="quart", websocket_callbacks=True)
    app.layout = html.Div(
        [
            html.Button("p", id="priv-in"),
            html.Div("idle", id="priv-out"),
            html.Button("u", id="pub-in"),
            html.Div("idle", id="pub-out"),
        ]
    )

    @callback(
        Output("priv-out", "children"),
        Input("priv-in", "n_clicks"),
        prevent_initial_call=True,
        websocket=True,
    )
    def private(_n):
        return "TOP-SECRET-USER-DATA"

    @public_callback(
        Output("pub-out", "children"),
        Input("pub-in", "n_clicks"),
        prevent_initial_call=True,
        websocket=True,
    )
    async def public(_n):
        return "PUBLIC-OK"

    BasicAuth(app, {"hello": "world"}, secret_key="Test!")
    return app


def _build_app_with_protected_admin_callback() -> Dash:
    """App whose private callback is group-gated to ``admin`` over the socket."""
    app = Dash(__name__, backend="quart", websocket_callbacks=True)
    app.layout = html.Div(
        [
            html.Button("p", id="priv-in"),
            html.Div("idle", id="priv-out"),
        ]
    )

    @protected_callback(
        Output("priv-out", "children"),
        Input("priv-in", "n_clicks"),
        groups=["admin"],
        missing_permissions_output="forbidden",
        prevent_initial_call=True,
        websocket=True,
    )
    async def private(_n):
        return "TOP-SECRET-ADMIN-DATA"

    BasicAuth(
        app,
        {"admin": "pw", "viewer": "pw"},
        user_groups={"admin": ["admin"]},  # "viewer" authenticates with no groups
        secret_key="Test!",
    )
    return app


def _login_cookie_header(base_url, username, password) -> str:
    """Authenticate over HTTP and return the session ``Cookie`` header value.

    The before_request hook runs ``is_authorized`` on this request, which
    stashes ``session["user"]`` (with the user's groups) and sets the session
    cookie -- the same cookie the browser would send at the WS handshake.
    """
    resp = requests.get(base_url, auth=(username, password), timeout=8)
    assert resp.status_code == 200, resp.status_code
    return "; ".join(f"{c.name}={c.value}" for c in resp.cookies)


def _send_callback_request(ws_url, origin, output, comp_id, in_id, cookie=None):
    header = [f"Origin: {origin}"]
    if cookie:
        header.append(f"Cookie: {cookie}")
    conn = websocket.create_connection(ws_url, header=header, timeout=8)
    try:
        conn.send(
            json.dumps(
                {
                    "type": "callback_request",
                    "requestId": "1",
                    "rendererId": "r1",
                    "payload": {
                        "output": output,
                        "outputs": {"id": comp_id, "property": "children"},
                        "inputs": [{"id": in_id, "property": "n_clicks", "value": 1}],
                        "changedPropIds": [f"{in_id}.n_clicks"],
                        "state": [],
                    },
                }
            )
        )
        frames = []
        for _ in range(5):
            try:
                frames.append(str(conn.recv()))
            except Exception:
                break
        return "".join(frames)
    finally:
        try:
            conn.close()
        except Exception:
            pass


def test_unauthenticated_ws_cannot_invoke_private_callback(dash_thread_server):
    app = _build_app()
    dash_thread_server(app)
    base = dash_thread_server.url
    ws_url = base.replace("http://", "ws://") + "/_dash-ws-callback"

    received = _send_callback_request(
        ws_url, base, "priv-out.children", "priv-out", "priv-in"
    )
    assert "TOP-SECRET-USER-DATA" not in received


def test_unauthenticated_ws_can_invoke_public_callback(dash_thread_server):
    app = _build_app()
    dash_thread_server(app)
    base = dash_thread_server.url
    ws_url = base.replace("http://", "ws://") + "/_dash-ws-callback"

    received = _send_callback_request(
        ws_url, base, "pub-out.children", "pub-out", "pub-in"
    )
    assert "PUBLIC-OK" in received


def test_authenticated_wrong_group_ws_gets_fallback_not_secret(dash_thread_server):
    """Authenticated-but-under-privileged over the raw socket: the group gate
    renders ``missing_permissions_output`` and never leaks the admin payload.
    """
    app = _build_app_with_protected_admin_callback()
    dash_thread_server(app)
    base = dash_thread_server.url
    ws_url = base.replace("http://", "ws://") + "/_dash-ws-callback"

    # "viewer" authenticates (cookie set) but lacks the "admin" group.
    cookie = _login_cookie_header(base, "viewer", "pw")

    received = _send_callback_request(
        ws_url, base, "priv-out.children", "priv-out", "priv-in", cookie=cookie
    )
    assert "TOP-SECRET-ADMIN-DATA" not in received
    assert "forbidden" in received
