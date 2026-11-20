"""Authentication and authorization for Dash apps on sync and async backends."""

from importlib.metadata import version as _version

from ._optional import OIDCAuth, get_oauth
from .auth import Auth
from .backends import Backend, FastAPIBackend, FlaskBackend, QuartBackend
from .basic_auth import BasicAuth
from .group_protection import check_groups, list_groups, protected, protected_callback
from .public_routes import add_public_routes, get_url_base, public_callback

__version__ = _version("dash-auth-async")

__all__ = [
    "Auth",
    "Backend",
    "BasicAuth",
    "FastAPIBackend",
    "FlaskBackend",
    "OIDCAuth",
    "QuartBackend",
    "__version__",
    "add_public_routes",
    "check_groups",
    "get_oauth",
    "get_url_base",
    "list_groups",
    "protected",
    "protected_callback",
    "public_callback",
]
