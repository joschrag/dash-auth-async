"""Authentication and authorization for Dash apps on sync and async backends."""

from .basic_auth import BasicAuth
from .group_protection import check_groups, list_groups, protected, protected_callback
from .public_routes import add_public_routes, public_callback

# oidc auth requires authlib, install with `pip install dash-auth[oidc]`
try:
    from .oidc_auth import OIDCAuth, get_oauth
except ModuleNotFoundError:
    pass
from .version import __version__

__all__ = [
    "BasicAuth",
    "OIDCAuth",
    "__version__",
    "add_public_routes",
    "check_groups",
    "get_oauth",
    "list_groups",
    "protected",
    "protected_callback",
    "public_callback",
]
