## Dash Authorization and Login

![Lint](https://github.com/joschrag/dash-auth-async/actions/workflows/lint.yml/badge.svg)
![Typecheck](https://github.com/joschrag/dash-auth-async/actions/workflows/typecheck.yml/badge.svg)
[![codecov](https://codecov.io/gh/joschrag/dash-auth-async/branch/main/graph/badge.svg)](https://codecov.io/gh/joschrag/dash-auth-async)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![ty](https://img.shields.io/badge/type--checked-ty-blue)](https://github.com/astral-sh/ty)
[![PyPI](https://img.shields.io/pypi/v/dash-auth-async)](https://pypi.org/project/dash-auth-async/)
![Python](https://img.shields.io/pypi/pyversions/dash-auth-async)
![License](https://img.shields.io/pypi/l/dash-auth-async)

Maintained by [joschrag](https://github.com/joschrag/). Forked from [plotly/dash-auth](https://github.com/plotly/dash-auth) with the goal to add support for the new 4.x dash backends.

License: MIT

## Feature overview

How this fork compares to upstream [`dash-auth`](https://github.com/plotly/dash-auth). The headline difference is async: upstream is Flask-only, while `dash-auth-async` adds async callback support, the Quart and FastAPI backends, authenticated WebSocket callbacks, and a pluggable backend abstraction. 

| Capability | `dash-auth` (upstream) | `dash-auth-async` |
| --- | :---: | :---: |
| Flask backend | ✅ | ✅ |
| Quart backend | ❌ | ✅ |
| FastAPI backend | ❌ | ✅ |
| Custom backends | ❌ | ✅ <sup>1</sup> |
| Protected / public callbacks | ✅ | ✅ |
| Async callbacks | ❌ | ✅ <sup>2</sup> |
| Authenticated WebSocket callbacks | ❌ | ✅ <sup>3</sup> |
| Group-protected background callbacks | ❌ | ✅ <sup>4</sup> |
| Protected / public streaming callbacks | ❌ | ✅ <sup>5</sup> |

✅ supported · ❌ not supported

<sup>1</sup> `detect_backend` resolves Flask/Quart/FastAPI automatically; any other server is supported by supplying your own `Backend` instance.

<sup>2</sup> Supported on **every** backend, Flask included — you don't need Quart or FastAPI, just the `async` extra (bundled as `dash-auth-async[async]`, which pulls in `dash[async]`).

<sup>3</sup> Provided by the Quart and FastAPI backends only. WebSocket auth is a no-op on Flask, which has no WebSocket callback transport.

<sup>4</sup> `protected_callback(..., background=True)` checks the user's groups when the request arrives — on the start request and every poll — so a denied user gets the fallback output without a job ever being started. The job itself runs in a separate process with no session, which is why the check can't live inside it (upstream checks there, so a background job always sees "no user" and is denied). Needs a background manager, e.g. `dash[diskcache]`. These callbacks are refused over the WebSocket; Dash only sends background callbacks over HTTP.

<sup>5</sup> Dash 4.5+ streaming callbacks (`async def` callbacks that `yield`) work with `protected_callback` and `public_callback`. Dash consumes a stream outside the request, where no session is readable, so the caller is captured while Dash dispatches the callback and the group check runs with that user when the stream starts — over inline HTTP, the shared-storage downlink and the WebSocket alike. An allowed user receives every chunk; a denied user gets the fallback output as a stream frame. Public streams also reach anonymous visitors when the app uses shared storage. Sync generators are rejected by Dash itself. Logging out with `OIDCAuth` also stops the protected streams that session started, in every open tab: within about a second the stream sends its `unauthenticated_output` and ends (WebSocket streams end because logout closes the socket). Sessions ended any other way — expiry, or clearing the session yourself — do not stop running streams.

## Installation

Python 3.11+ and Dash 3+ are required.

```bash
pip install dash-auth-async                 # Flask + BasicAuth
pip install "dash-auth-async[oidc]"         # + OpenID Connect
pip install "dash-auth-async[quart]"        # + Quart backend
pip install "dash-auth-async[fastapi]"      # + FastAPI backend
pip install "dash-auth-async[async]"        # + async callbacks on Flask
```

Extras combine, e.g. `dash-auth-async[oidc,fastapi]`.

## Quickstart

```python
from dash import Dash
from dash_auth_async import BasicAuth

app = Dash(__name__)  # or backend="quart" / backend="fastapi"
BasicAuth(app, {"username": "password"})
```

## Documentation

| Guide | Covers |
| --- | --- |
| [Basic Authentication](https://github.com/joschrag/dash-auth-async/blob/main/docs/basic-auth.md) | Username/password dicts and custom auth functions |
| [Public routes](https://github.com/joschrag/dash-auth-async/blob/main/docs/public-routes.md) | `add_public_routes`, `public_callback`, multi-page apps |
| [OIDC Authentication](https://github.com/joschrag/dash-auth-async/blob/main/docs/oidc.md) | OpenID Connect, reverse proxies, multiple providers |
| [Async backends](https://github.com/joschrag/dash-auth-async/blob/main/docs/async-backends.md) | Quart and FastAPI setup, WebSocket callback limitations |
| [User-group-based permissions](https://github.com/joschrag/dash-auth-async/blob/main/docs/groups.md) | `list_groups`, `check_groups`, `protected`, `protected_callback` |

## Upgrading to 2.0

2.0 changes how the package installs. Code using `BasicAuth`, `OIDCAuth` and the group helpers is unchanged.

1. **OIDC users:** add the `oidc` extra — `pip install dash-auth-async[oidc]` (plus `quart`/`fastapi` if you use those backends). Without it, `OIDCAuth` raises an `ImportError` naming the extra.
2. **Python 3.11+** and **Dash 3+** are now required.
3. **`dash_auth_async.version` is gone.** Read the version from `dash_auth_async.__version__`.
4. **OIDC refresh tokens are no longer stored in `session["refresh_token"]`** (the cookie is readable by the client). If you need one, capture it in an `after_logged_in` override and store it server-side — see the CHANGELOG for an example.

See [CHANGELOG.md](https://github.com/joschrag/dash-auth-async/blob/main/CHANGELOG.md) for the full list.

## Contributing

See [CONTRIBUTING.md](https://github.com/joschrag/dash-auth-async/blob/main/CONTRIBUTING.md).
