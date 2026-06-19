"""Regression: logging in must close the same browser's stale pre-login socket.

A WebSocket's session is frozen at the handshake cookie. A socket opened before
login is therefore permanently unauthenticated, and Dash's renderer only
reconnects on a socket *close* -- so without intervention the first protected
callback over that socket is rejected (4401) and silently dropped, and the user
must click a second time (the rejection is what finally triggers the reconnect).

Design A closes that gap from the server: a pre-login ``dac_client`` cookie ties
an anonymous socket back to the browser, and the moment that browser
authenticates over HTTP the server closes its stale anonymous socket. The
renderer's existing auto-reconnect then dials a fresh, authenticated handshake
*before* the first click.

This test drives the raw socket (no browser) and asserts that proactive close.
FastAPI sibling of the Quart variant.
"""

import pytest
from dash import Dash, Input, Output, callback, html

from dash_auth_async import BasicAuth

pytest.importorskip("fastapi", reason="FastAPI extra dependencies are not installed")
requests = pytest.importorskip("requests", reason="requests is not installed")
websocket = pytest.importorskip(
    "websocket", reason="websocket-client (the 'websocket' module) is not installed"
)


def _build_app() -> Dash:
    app = Dash(__name__, backend="fastapi", websocket_callbacks=True)
    app.layout = html.Div(
        [html.Button("p", id="priv-in"), html.Div("idle", id="priv-out")]
    )

    @callback(
        Output("priv-out", "children"),
        Input("priv-in", "n_clicks"),
        prevent_initial_call=True,
        websocket=True,
    )
    def private(_n):
        return "TOP-SECRET-USER-DATA"

    BasicAuth(app, {"hello": "world"}, secret_key="Test!")
    return app


def _socket_was_closed(conn, timeout=6) -> bool:
    """Return True if the server closed ``conn`` within ``timeout`` seconds.

    websocket-client surfaces a server close as an empty ``recv()`` or a
    ``WebSocketConnectionClosedException``; a still-open idle socket raises a
    timeout instead.
    """
    conn.settimeout(timeout)
    try:
        return conn.recv() in {"", b"", None}
    except websocket.WebSocketConnectionClosedException:
        return True
    except Exception:
        return False


def test_login_closes_stale_anonymous_socket(dash_thread_server):
    app = _build_app()
    dash_thread_server(app)
    base = dash_thread_server.url
    ws_url = base.replace("http://", "ws://") + "/_dash-ws-callback"

    session = requests.Session()

    # First anonymous contact must mint a pre-login client-id cookie -- even on
    # the BasicAuth 401 challenge -- so the socket can be tied to this browser.
    session.get(base, timeout=8)
    client_id = session.cookies.get("dac_client")
    assert client_id, "expected a pre-login 'dac_client' cookie on first contact"

    # Open an anonymous socket carrying only dac_client (no session): this models
    # the SharedWorker socket opened on a public page before login.
    conn = websocket.create_connection(
        ws_url,
        header=[f"Origin: {base}", f"Cookie: dac_client={client_id}"],
        timeout=8,
        suppress_origin=True,
    )
    try:
        # The same browser now authenticates over HTTP (same dac_client cookie).
        resp = session.get(base, auth=("hello", "world"), timeout=8)
        assert resp.status_code == 200, resp.status_code

        # The server must proactively close the stale anonymous socket so the
        # renderer reconnects authenticated before the user's first click.
        assert _socket_was_closed(conn), (
            "stale pre-login socket was not closed after the same browser "
            "logged in -- the first protected click would be dropped"
        )
    finally:
        try:
            conn.close()
        except Exception:
            pass
