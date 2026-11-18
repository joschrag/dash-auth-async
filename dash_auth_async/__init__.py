"""Authentication and authorization for Dash apps on sync and async backends."""

from importlib.metadata import version as _version

from ._optional import OIDCAuth, get_oauth
from .basic_auth import BasicAuth
from .group_protection import check_groups, list_groups, protected, protected_callback
from .public_routes import add_public_routes, public_callback

__version__ = _version("dash-auth-async")

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
