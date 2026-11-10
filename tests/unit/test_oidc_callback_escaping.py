"""The OIDC callback route must not reflect request-controlled text as HTML.

The route is public (it has to be, to complete a login), and Flask/Quart render
a returned ``str`` as ``text/html``. Both the ``<idp>`` path segment and the
IdP's ``error_description`` query parameter are attacker-controlled, so echoing
them unescaped is a reflected XSS in the app's origin.
"""

import asyncio

import pytest
from dash import Dash, html

from dash_auth_async import OIDCAuth

pytestmark = pytest.mark.usefixtures("reset_active_backend")

IDP_URL = "/oidc/%3Cimg%20src=x%20onerror=alert(1)%3E/callback"
ERROR_URL = (
    "/oidc/idp/callback?error=x&error_description=%3Cscript%3Ealert(1)%3C/script%3E"
)


def _oidc_app(backend):
    kwargs = {} if backend == "flask" else {"backend": backend}
    app = Dash(f"oidc_escaping_{backend}", **kwargs)
    app.layout = html.Div("hi")
    oidc = OIDCAuth(app, secret_key="Test")
    oidc.register_provider(
        "idp",
        client_id="x",
        client_secret="y",
        authorize_url="https://idp.example/auth",
        access_token_url="https://idp.example/token",
    )
    return app


def _get(backend, url):
    """Return ``(status, body)`` for a GET against a fresh app on ``backend``."""
    if backend == "quart":
        pytest.importorskip("quart")
    if backend == "fastapi":
        pytest.importorskip("fastapi")
    app = _oidc_app(backend)
    if backend == "flask":
        response = app.server.test_client().get(url)
        return response.status_code, response.get_data(as_text=True)
    if backend == "quart":

        async def run():
            response = await app.server.test_client().get(url)
            return response.status_code, await response.get_data(as_text=True)

        return asyncio.run(run())

    from starlette.testclient import TestClient

    response = TestClient(app.server).get(url)
    return response.status_code, response.text


@pytest.mark.parametrize("backend", ["flask", "quart", "fastapi"])
def test_unknown_idp_is_not_reflected_as_html(backend):
    status, body = _get(backend, IDP_URL)
    assert status == 400
    assert "<img" not in body


@pytest.mark.parametrize("backend", ["flask", "quart", "fastapi"])
def test_idp_error_description_is_not_reflected_as_html(backend):
    status, body = _get(backend, ERROR_URL)
    assert status == 401
    assert "<script>" not in body
