# OIDC Authentication

OIDC needs authlib, shipped as the `oidc` extra:

```bash
pip install dash-auth-async[oidc]
```

To add authentication with OpenID Connect, you will first need to set up an OpenID Connect provider (IDP).
This typically requires creating
* An application in your IDP
* Defining the redirect URI for your application, for testing locally you can use http://localhost:8050/oidc/callback
* A client ID and secret for the application

Once you have set up your IDP, you can add it to your Dash app as follows:

```python
from dash import Dash
from dash_auth_async import OIDCAuth

app = Dash(__name__)

auth = OIDCAuth(app, secret_key="aStaticSecretKey!")
auth.register_provider(
    "idp",
    token_endpoint_auth_method="client_secret_post",
    # Replace the below values with your own
    # NOTE: Do not hardcode your client secret!
    client_id="<my-client-id>",
    client_secret="<my-client-secret>",
    server_metadata_url="<my-idp-.well-known-configuration>",
)
```

Once this is done, connecting to your app will automatically redirect to the IDP login page.

## Running behind a reverse proxy

> **Behavior change.** Earlier versions rewrote the OIDC callback host from the
> client-supplied `X-Forwarded-Host` header. That header trust was **removed** — an
> attacker could set it to steer the `redirect_uri` handed to your IDP (auth-code leak /
> open redirect). The `redirect_uri` is now built **only** from the host and scheme of
> the incoming request.

The consequence: behind a proxy that terminates TLS or rewrites the host, the
`redirect_uri` comes out as `http://localhost:8050/...` and your IDP rejects it. To get
the real public host and scheme back, **restore it at the transport layer** — where the
trust can be bounded to your actual proxy, instead of trusting any client.

Two separate things to restore: **scheme** (http→https) and **host**. Most app servers
forward the scheme but **not** the host — `--forwarded-allow-ips` / `--proxy-headers`
only governs `X-Forwarded-Proto`/`-For`, never the host. So:

* **Scheme:** set `force_https_callback=True` on `OIDCAuth` (or pass the name of an env
  var that, when present, enables it). This covers the http→https half on every backend.
* **Host:** add proxy middleware that honours `X-Forwarded-Host`, sized to your real
  proxy-chain length:

| Backend | Server(s) | How to restore the host |
|---|---|---|
| **Flask** | gunicorn, waitress, mod_wsgi, … | `werkzeug` `ProxyFix` on the WSGI app (server-independent — gunicorn alone won't do the host) |
| **Quart** | hypercorn | `ProxyFixMiddleware(mode="modern", trusted_hops=N)` — restores host and scheme |
| **Quart / FastAPI** | uvicorn | uvicorn `--proxy-headers` does scheme only; add an `X-Forwarded-Host` ASGI middleware or have the proxy rewrite the `Host` header |

**Flask** (WSGI — gunicorn, waitress, …):

```python
from werkzeug.middleware.proxy_fix import ProxyFix

# Counts MUST equal your real proxy-chain length — setting them higher than the
# actual chain (or enabling this with no proxy) re-opens the spoofing hole.
app.server.wsgi_app = ProxyFix(app.server.wsgi_app, x_for=1, x_proto=1, x_host=1)
```

**Quart** (served by hypercorn) — wrap the ASGI app:

```python
from hypercorn.middleware import ProxyFixMiddleware

# trusted_hops MUST equal your real proxy-chain length (see warning below).
app.server.asgi_app = ProxyFixMiddleware(app.server.asgi_app, mode="modern", trusted_hops=1)
```

**FastAPI / Quart on uvicorn:** uvicorn restores the scheme (`--proxy-headers
--forwarded-allow-ips=...`) but **not** the host. Either have your proxy overwrite the
`Host` header with the public host, or add a small trusted ASGI middleware that copies
`X-Forwarded-Host` onto the `host` header — same `trusted_hops` discipline as above.

> ⚠️ Only restore proxy-header trust when a real proxy sets those headers, and set the
> hop counts to the actual chain length. A trusted-host middleware in front of *no*
> proxy lets a client spoof the host again — which is exactly the trust that was removed.

## Multiple OIDC Providers

For multiple OIDC providers, you can use `register_provider` to add new ones after the OIDCAuth has been instantiated.

```python
from dash import Dash, html
from dash_auth_async import OIDCAuth
from flask import request, redirect, url_for

app = Dash(__name__)

app.layout = html.Div([
    html.Div("Hello world!"),
    html.A("Logout", href="/oidc/logout"),
])

auth = OIDCAuth(
    app,
    secret_key="aStaticSecretKey!",
    # Set the route at which the user will select the IDP they wish to login with
    idp_selection_route="/login",
)
auth.register_provider(
    "IDP 1",
    token_endpoint_auth_method="client_secret_post",
    client_id="<my-client-id>",
    client_secret="<my-client-secret>",
    server_metadata_url="<my-idp-.well-known-configuration>",
)
auth.register_provider(
    "IDP 2",
    token_endpoint_auth_method="client_secret_post",
    client_id="<my-client-id2>",
    client_secret="<my-client-secret2>",
    server_metadata_url="<my-idp2-.well-known-configuration>",
)

@app.server.route("/login", methods=["GET", "POST"])
def login_handler():
    if request.method == "POST":
        idp = request.form.get("idp")
    else:
        idp = request.args.get("idp")

    if idp is not None:
        return redirect(url_for("oidc_login", idp=idp))

    return """<div>
        <form>
            <div>How do you wish to sign in:</div>
            <select name="idp">
                <option value="IDP 1">IDP 1</option>
                <option value="IDP 2">IDP 2</option>
            </select>
            <input type="submit" value="Login">
        </form>
    </div>"""


if __name__ == "__main__":
    app.run(debug=True)
```
