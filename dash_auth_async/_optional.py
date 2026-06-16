"""Optional re-exports whose dependencies are not always installed.

``OIDCAuth`` and ``get_oauth`` require authlib
(``pip install dash-auth-async[oidc]``). When it is missing they resolve to
``None`` at runtime so importing the package never fails; attempting to use
``OIDCAuth`` without authlib then raises a clear error at the call site.

This logic lives here, rather than in ``__init__``, so the package's
``__init__`` stays a pure re-export facade. Type-checkers see the real symbols
(authlib assumed present); the runtime ``None`` fallback is invisible to them.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .oidc_auth import OIDCAuth, get_oauth
else:
    try:
        from .oidc_auth import OIDCAuth, get_oauth
    except ModuleNotFoundError:
        OIDCAuth = None
        get_oauth = None

__all__ = ["OIDCAuth", "get_oauth"]
