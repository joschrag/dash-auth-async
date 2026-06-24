# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](http://keepachangelog.com/en/1.0.0/)
and this project adheres to [Semantic Versioning](http://semver.org/spec/v2.0.0.html).

## [1.3.3] - 2026-06-24

### Security
- `OIDCAuth` no longer rewrites the callback host from the client-supplied `X-Forwarded-Host` header when building the IDP `redirect_uri`. An attacker could set that header to point the `redirect_uri` at a host they control, leaking the authorization code (or acting as an open-redirect / phishing primitive). The `redirect_uri` is now derived only from the host and scheme of the incoming request.

### Changed
- **Behavior change for proxied OIDC deployments.** Because `X-Forwarded-Host` is no longer trusted, apps behind a reverse proxy that rewrites the host must restore the public host at the transport layer (e.g. werkzeug `ProxyFix` on Flask, hypercorn `ProxyFixMiddleware` on Quart, or a proxy that overwrites the `Host` header on uvicorn). `force_https_callback` continues to cover the scheme. See the "Running behind a reverse proxy" section of the README.

## [1.3.2] - 2026-06-24

### Fixed
- `BasicAuth` credential checks now run in constant time even for unknown usernames, closing a timing side channel that allowed username enumeration
- Callback requests whose body is missing the `inputs` key now fail closed (treated as unauthorised) instead of raising a server error
- `public_callback` derives its callback id from the output spec (`create_callback_id`) rather than the function source text or a diff of Dash's process-global `GLOBAL_CALLBACK_MAP`. Re-registering the same output id (a second app in the same process, or repeated registration) added no new map key, so the diff came back empty and the callback was whitelisted as `None` — leaving the route unauthenticated over WebSocket

## [1.3.1] - 2026-06-19

### Fixed
- FastAPI page routes no longer return a `500` ("No active request in context") under Dash 4.3.0. Dash 4.3.0's middleware skips setting its request context for non-`_dash-` page routes; the FastAPI backend now backfills that context itself so page routes (and the catch-all `index()`) render correctly

## [1.3.0] - 2026-06-19

### Added
- FastAPI (async) backend support for `BasicAuth` and `OIDCAuth` — run on Starlette/ASGI with `Dash(__name__, backend="fastapi")`. Auth is enforced by pure-ASGI middleware, sessions use Starlette `SessionMiddleware`, and public routes/callbacks are stored on the app's `server.state`
- Authenticated WebSocket callbacks on the FastAPI backend: each `callback_request` is authorized via `Backend.ws_identity` and fails closed, while public callbacks still stream unauthenticated
- WebSocket authentication now reconnects on login. When a browser authenticates over HTTP, its stale pre-login WebSocket is retired so the renderer reconnects with the authenticated session — eliminating the "first click is dropped / only works on the second click" behaviour for callbacks invoked over a socket opened before login. Applies to both the FastAPI and Quart backends

### Changed
- The WebSocket `callback_map` is migrated lazily on the first `callback_request` rather than at `Auth(...)` construction, so a global `@callback` registered after `Auth(...)` is still picked up and a WebSocket-first client no longer hits an empty map

### Fixed
- The public-route helpers resolve the backend from `app.server` instead of a process-global fallback, keeping routing correct when several apps share a process
- `secure_session` is honoured through `setup_session`, and the FastAPI session lookup is hardened so it raises a clear error (rather than `KeyError`) under `python -O`
- FastAPI OIDC views annotate their request parameter so Starlette injects the request, and the ASGI body-replay emits `http.disconnect` once the cached body is consumed

## [1.2.1] - 2026-06-17

### Fixed
- `BasicAuth` now returns a `401` login response instead of a `500` server error when the `Authorization` header is missing or malformed
- `BasicAuth` password verification uses a constant-time comparison, removing a timing side channel during credential checks

## [1.2.0] - 2026-06-16

### Added
- Authenticated WebSocket callbacks on the Quart backend: the global `websocket_message` hook authorizes every `callback_request` and fails closed, closing the prior unauthenticated-callback bypass
- `Auth.authorize_ws()` — session-based authorization decision for WebSocket callbacks
- `enable_ws_auth` and a context-copying executor that propagates the authenticated user into Dash's callback worker threads
- Feature overview matrix in the README comparing `dash-auth-async` with upstream `dash-auth`

### Fixed
- `protected_callback` no longer strips async callbacks to plain functions, so coroutine callbacks stay async through protection and are awaited by Dash
- Group gating resolves the caller via `_current_user`, so it fails closed over WebSocket where no request-context session is available

## [1.1.0] - 2026-06-13

### Added
- Async Quart backend support for both `BasicAuth` and `OIDCAuth` — use `Dash(__name__, backend="quart")` to run on the async Quart server
- `quart_client` module: Quart-native OAuth integration built on authlib's async mixins (`AsyncOAuth2Mixin`, `AsyncOpenIDMixin`)
- Backend abstraction layer (`FlaskBackend`, `QuartBackend`) with automatic detection via `detect_backend()`
- `httpx` dependency added to the `quart` optional extra for async HTTP in the OAuth flow
- CI matrix splits for testing Dash 4.x with and without async backends

### Changed
- `OIDCAuth` internals refactored to use framework-agnostic `backend.url_for()` and `backend.redirect()` instead of importing Flask directly

### Fixed
- Handle `TestRunner` lacking `_app` attribute on Dash < 4.2.0

## [1.0.0] - 2026-06-11

> First release as `dash-auth-async`, forked from [plotly/dash-auth](https://github.com/plotly/dash-auth) at v2.3.0.

### Added
- GitHub Actions CI with matrix testing across Python 3.10–3.13 and Dash 3.x / 4.x
- `LICENSE` file (MIT, covering both Plotly's original work and fork contributions)

### Changed
- Package renamed to `dash-auth-async`
- Migrated packaging from `setup.py` to `pyproject.toml`
- Raised minimum Python version to 3.10
- Switched type checker from mypy to [ty](https://github.com/astral-sh/ty)

### Fixed
- Fix public routes being protected when passing `url_base_pathname` or `routes_pathname_prefix` to app
- Fix OIDC redirects after login and logout when passing `url_base_pathname` or `routes_pathname_prefix` to app
- Fix `get_url_base` using `requests_pathname_prefix` (client-side) instead of `routes_pathname_prefix` (server-side) as fallback
- Fix type errors reported by ty in `basic_auth.py` and `oidc_auth.py`

---

## History inherited from [plotly/dash-auth](https://github.com/plotly/dash-auth)

## [2.3.0] - 2024-03-18
### Added
- OIDCAuth allows to authenticate via OIDC
- BasicAuth saves the current user in the session
- Ability to define user groups in BasicAuth
- Group-based permission and protection functions

## [2.2.1] - 2024-03-01
### Fixed
- Fix when looking for callback inputs that are not in the right format when checking for whitelisted routes

## [2.2.0] - 2024-02-05
### Added
- Possibility to whitelist routes with the `add_public_routes` utility function, the routes should follow Flask route syntax
- NOTE: If you are using server-side callbacks on your public routes, you should use dash_auth's new `public_callback` rather than the default Dash callback

## [2.1.0] - 2024-01-24
### Changed
- Uses flask `before_request` to protect all endpoints rather than protecting routes present at instantiation time
- Allows user to use user-defined authorization python function instead of a dictionary/list of usernames and passwords
- Raise minimum Python version to 3.8, dropping support for 3.6 and 3.7

## [2.0.0] - 2023-03-10
### Removed
Removed obsolete `PlotlyAuth`. `dash-auth` is now just responsible for `BasicAuth`.
Drop Python 2 support. Minimum Python version is now 3.6.

## [1.4.1] - 2019-10-04
### Fixed
Fixed a bug with PlotlyAuth not properly converting user data to json

## [1.4.0] - 2019-09-02
### Changed
Updated to require dash 1.x - this did not affect the API of this package at all, but usage examples and tests were adapted for the dash API changes.

## [1.3.2] - 2018-12-18
### Change
Changed basic-auth to use a dictionary of valid credentials, rather than lists.
This ensures only one valid password per user, and credential checks are faster.

## [1.3.1] - 2018-12-05
### Changed
Changed the deprecation notice to only 2 repos (`dash-basic-auth` and `dash-enterprise-auth`).
The oauth abstraction can still be used with dash-auth.

## [1.3.0] - 2018-12-04

Add integrations with Dash Deployment Server 2.6. [#75](https://github.com/plotly/dash-auth/pull/75)
This version works on both 2.5 and 2.6.

dash-auth will be split into 2 repositories:

- `dash-basic-auth` -> basic_auth
- `dash-enterprise-auth` -> Dash Deployment Server integration, replace PlotlyAuth.

### Added
- Pending deprecation notice for PlotlyAuth.

### Changed
- Logout button changed to a `dcc.LogoutButton` if app is on Dash Deployment Server 2.6
- `get_username` from request headers if app is on Dash Deployment Server 2.6
- Disabled authentication if app is on Dash Deployment Server>=2.6, authentication is now performed on the Dash Deployment Server for all deployed apps.

### Fixed
- Fixed logout invalidation url and put in a try/catch so the token is still cleared from the cookies after an error.

## [1.2.0] - 2018-10-11
### Fixed
- Kerberos tickets can be retrieved from a Dash Deployment Server and used
to perform multi-hop authentication. [#64](https://github.com/plotly/dash-auth/pull/64)

## [1.1.4] - 2018-09-11
### Fixed
- Token invalidation from self signed on-prem. [#56](https://github.com/plotly/dash-auth/pull/56)
- Logout button redirect to app url. [#56](https://github.com/plotly/dash-auth/pull/56)
- Cookie clear use `requests_pathname_prefix`. [#56](https://github.com/plotly/dash-auth/pull/56)

## [1.1.3] - 2018-09-12
### Fixed
- Detect requests coming from orca pdf generation and disable unsupported secure cookies. [#60](https://github.com/plotly/dash-auth/pull/60)

## [1.1.2] - 2018-08-15
### Fixed
- Remove trailing slash from the cookie path.

## [1.1.1] - 2018-08-14
### Fixed
- Cookies path take `requests_pathname_prefix` instead of `routes`. [#54](https://github.com/plotly/dash-auth/pull/54)
- Ensure failed cookie unsign clear the cookies.

## [1.1.0] - 2018-08-10
### Added
- Added `get_username` to `PlotlyAuth`, signed cookie stored in `USERNAME_COOKIE`.
- Added `get_user_data` to `PlotlyAuth`, custom cookie that can contains any json data for the user.
- Added `logout` to `PlotlyAuth`, helper method to remove the auth cookies and invalidate the token.
- Added `create_logout_button` which create a dash logout button that will logout on click to be inserted in the layout.

## [1.0.2] - 2018-05-31
### Fixed
- Use update_or_create for OAuth app creation when available, to avoid
  race condition.

## [1.0.1] - 2018-05-02
### Fixed
- Handle the case where more than one OAuth app exists in streambed.

## [1.0.0] - 2018-04-11
### Added
- `PlotlyAuth` now supports "secret" authentication using the `share_key`
parameter.

### Changed
- All `Auth` subclasses must now implement `index_auth_wrapper()`. See
`basic_auth.py` for an example that preserves the existing behaviour.

## [0.1.0] - 2018-03-27
### Added
- `PlotlyAuth` now supports multiple URLs. Supply a localhost URL and a remote
URL in order to test your Plotly login on your local machine while keeping
the login screen available in your deployed app. Usage:
```
dash_auth.PlotlyAuth(app, 'my-app', 'private', [
    'https://my-deployed-dash-app.com',
    'http://localhost:8050'
])
```
See https://github.com/plotly/dash-auth/pull/29

### Fixed
- `PlotlyAuth` is now stateless. This allows `PlotlyAuth` to be
used in Dash Apps that are deployed with multiple workers.
See https://github.com/plotly/dash-auth/pull/32

## [0.0.11] - 2018-02-01
### Added
- Added logging on request failure for the `PlotlyAuth` handler
- Added retry logic for the `PlotlyAuth` handler

## [0.0.10] - 2017-10-05
### Fixed
- The oauth redirect URL is now trailing-backslash insensitive

## [0.0.9] - 2017-10-02
### Fixed
- Allow the version to be imported with `dash_auth.__version__`

## [0.0.8] - 2017-09-26
### Fixed
- Wrap string responses in a `flask.Response` so that cookies can be added to it

## [0.0.7] - 2017-09-19
### Fixed
- Fixed authentication with path based routing with dash==0.18.3
### Added
- Add path and secure attributes to the plotly auth cookies for `PlotlyAuth`
### Removed
- No longer implicitly saves `localhost:8050` as a valid oauth redirect URL for `PlotlyAuth`

## [0.0.6] - 2017-09-05
### Fixed
- Path-based routing with Plotly auth for apps where `app.config.requests_pathname_prefix` is not `/` now works

## [0.0.5] - 2017-08-22
### Added
- Python 3 support for Basic Auth

## [0.0.4] - 2017-08-17
### Added
- Integration and continuous integration tests
- Python 3 support for Plotly Auth

## [0.0.4rc7] - 2017-08-09
First stable Python 2 release
