"""Regression: _create_redirect_uri must ignore client-supplied X-Forwarded-Host.

Trusting that header let an attacker steer the IdP redirect_uri (auth-code leak
/ open redirect). _create_redirect_uri only reads force_https_callback and
backend.url_for, so we exercise it as an unbound method with a stub backend.
"""

from types import SimpleNamespace

from dash_auth_async.oidc_auth import OIDCAuth


def _stub(spoof_header, force_https=False):
    # url_for echoes the requested scheme so the https branch is observable.
    backend = SimpleNamespace(
        url_for=lambda *a, _scheme="http", **k: (
            f"{_scheme}://legit.example.com/oidc/myidp/callback"
        ),
        # If the old rewrite came back, it would read these — assert it doesn't.
        current_host=lambda: "legit.example.com",
    )
    return SimpleNamespace(
        force_https_callback=force_https,
        backend=backend,
        request=SimpleNamespace(headers={"X-Forwarded-Host": spoof_header}),
    )


def test_redirect_uri_ignores_forwarded_host():
    uri = OIDCAuth._create_redirect_uri(_stub("evil.example.com"), "myidp")
    assert uri == "http://legit.example.com/oidc/myidp/callback"


def test_redirect_uri_forces_https_scheme():
    uri = OIDCAuth._create_redirect_uri(
        _stub("evil.example.com", force_https=True), "myidp"
    )
    assert uri == "https://legit.example.com/oidc/myidp/callback"
