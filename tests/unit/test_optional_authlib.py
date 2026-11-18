"""The package imports and BasicAuth works without the optional authlib dependency."""

import subprocess
import sys

# Setting sys.modules["authlib"] = None makes every authlib import raise
# ModuleNotFoundError, simulating an install without the `oidc` extra.
_SCRIPT = """
import sys
sys.modules["authlib"] = None
from dash import Dash
import dash_auth_async
dash_auth_async.BasicAuth(Dash(__name__), {"user": "pass"})
for name in ("OIDCAuth", "get_oauth"):
    try:
        getattr(dash_auth_async, name)(Dash(__name__))
    except ImportError as exc:
        assert "dash-auth-async[oidc]" in str(exc), exc
    else:
        raise AssertionError(f"{name} did not raise without authlib")
"""


def test_oa001_import_without_authlib():
    """Without authlib, BasicAuth works and OIDC raises an error naming the extra."""
    result = subprocess.run(
        [sys.executable, "-c", _SCRIPT], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
