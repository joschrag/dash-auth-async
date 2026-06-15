# Quart WebSockets + public/private auth example

A minimal multi-page Dash app on the **Quart** backend that combines:

- **WebSocket streaming callbacks** (`Dash(backend="quart", websocket_callbacks=True)`)
- **Public vs authenticated pages** via `dash-auth-async` `BasicAuth`

## Pages

| Route      | Access        | What it shows                          |
|------------|---------------|----------------------------------------|
| `/`        | public        | Landing page + navigation              |
| `/live`    | public        | Live counter/clock streamed over WS    |
| `/private` | authenticated | Simulated 0→100% progress task over WS |

## Run

```bash
pip install "dash-auth-async[quart]"   # or: uv sync, from the repo root
python examples/websocket_auth_quart/app.py
```

Open <http://127.0.0.1:8050/>. The `/private` page prompts for login:

- `admin` / `admin`
- `viewer` / `viewer123`

(Use `127.0.0.1` rather than `localhost`.)

## Note on WebSocket-layer authentication

Authentication is enforced at the **HTTP page level**: `/private` is a normal
HTTP GET that is auth-checked, so an anonymous user cannot load the page or start
its stream. This is what the public/private split demonstrates.

However, `dash-auth-async`'s auth hook is registered as `@server.before_request`,
which does **not** fire for WebSocket connections (Quart uses separate
`before_websocket` / `websocket_connect` hooks). The WebSocket callback route
(`/_dash-ws-callback`) is therefore **not independently auth-gated** — a
hand-crafted raw WS connection would bypass the check. Closing this gap properly
would mean adding auth via Dash's `websocket_connect` hook in the library, which
is out of scope for this example.
