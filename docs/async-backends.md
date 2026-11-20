# Async backends

## Known Limitations

> **⚠️ WebSocket callbacks & auth:**
> Do **not** enable `websocket_callbacks=True`
> globally on an authenticated `use_pages` app. The global flag routes *every*
> callback — including Dash's built-in page-routing callback — over the WebSocket,
> which bypasses the HTTP `before_request` auth guard where the login challenge is
> issued. Navigating to a protected page then hangs (the socket closes with `4401`
> and reconnect-loops) instead of prompting for login — the prompt appears only after
> a full page reload. Opt **individual** streaming callbacks into `websocket=True`
> instead, so routing and login stay on HTTP.


## Quart (async) Backend

`dash-auth-async` supports [Dash's Quart backend](https://dash.plotly.com/) for fully async request handling.
Install the `quart` extra to pull in the required dependencies:

```
pip install dash-auth-async[quart]
```

Then pass `backend="quart"` when creating your Dash app. The auth setup is identical
to the Flask examples in [Basic Authentication](basic-auth.md) and [OIDC](oidc.md) — no code changes required beyond the backend flag.

### BasicAuth with Quart

```python
from dash import Dash
from dash_auth_async import BasicAuth

app = Dash(__name__, backend="quart")

BasicAuth(app, {"admin": "admin", "viewer": "viewer123"})

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8050, debug=True)
```

### OIDCAuth with Quart

OIDC on Quart needs both extras:

```
pip install dash-auth-async[oidc,quart]
```

```python
import os
from dash import Dash, html
from dash_auth_async import OIDCAuth

app = Dash(__name__, backend="quart")

app.layout = html.Div([
    html.H2("OIDCAuth + Quart"),
    html.A("Logout", href="/oidc/logout"),
])

auth = OIDCAuth(app, secret_key="aStaticSecretKey!")
auth.register_provider(
    "myidp",
    client_id=os.environ["OIDC_CLIENT_ID"],
    client_secret=os.environ["OIDC_CLIENT_SECRET"],
    server_metadata_url=os.environ["OIDC_METADATA_URL"],
    token_endpoint_auth_method="client_secret_post",
    client_kwargs={"scope": "openid email profile"},
)

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8050, debug=True)
```

> **Note:** The Quart backend requires Dash >= 4.2.0 and Python >= 3.11.

## FastAPI (async) Backend

`dash-auth-async` supports [Dash's FastAPI backend](https://dash.plotly.com/) too.
Install the `fastapi` extra to pull in the required dependencies:

```
pip install dash-auth-async[fastapi]
```

Then pass `backend="fastapi"` when creating your Dash app. `BasicAuth` and
`OIDCAuth` work exactly as on Flask/Quart — no code changes beyond the backend flag.

### BasicAuth with FastAPI

```python
from dash import Dash
from dash_auth_async import BasicAuth

app = Dash(__name__, backend="fastapi")

BasicAuth(
    app,
    {"admin": "admin", "viewer": "viewer123"},
    secret_key="aStaticSecretKey!",  # enables sessions (SessionMiddleware)
)

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8050, debug=True)
```

### OIDCAuth with FastAPI

OIDC on FastAPI needs both extras:

```
pip install dash-auth-async[oidc,fastapi]
```

```python
import os
from dash import Dash, html
from dash_auth_async import OIDCAuth

app = Dash(__name__, backend="fastapi")

app.layout = html.Div([
    html.H2("OIDCAuth + FastAPI"),
    html.A("Logout", href="/oidc/logout"),
])

auth = OIDCAuth(app, secret_key="aStaticSecretKey!")
auth.register_provider(
    "myidp",
    client_id=os.environ["OIDC_CLIENT_ID"],
    client_secret=os.environ["OIDC_CLIENT_SECRET"],
    server_metadata_url=os.environ["OIDC_METADATA_URL"],
    token_endpoint_auth_method="client_secret_post",
    client_kwargs={"scope": "openid email profile"},
)

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8050, debug=True)
```

Notes:

- A `secret_key` installs Starlette's `SessionMiddleware` automatically. If you
  add your own `SessionMiddleware`, `dash-auth-async` defers to it.
- `Auth`/`OIDCAuth` must be constructed before the server starts serving
  (Starlette forbids adding middleware after startup) — the normal usage pattern.
- OIDC uses authlib's official `starlette_client`; no extra client module required.

> The FastAPI backend requires Dash >= 4.2.0 and Python >= 3.11.
