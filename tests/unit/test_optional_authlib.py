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
assert dash_auth_async.OIDCAuth is None
assert dash_auth_async.get_oauth is None
dash_auth_async.BasicAuth(Dash(__name__), {"user": "pass"})
"""


def test_oa001_import_without_authlib():
    """Importing the package and building BasicAuth must not require authlib."""
    result = subprocess.run(
        [sys.executable, "-c", _SCRIPT], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
