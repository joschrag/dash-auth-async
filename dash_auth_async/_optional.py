"""Optional re-exports whose dependencies are not always installed.

``OIDCAuth`` and ``get_oauth`` require authlib
(``pip install dash-auth-async[oidc]``). When it is missing they resolve to
stand-ins that raise an ``ImportError`` naming the extra when called, so
importing the package never fails but using OIDC without authlib fails loudly.

This logic lives here, rather than in ``__init__``, so the package's
``__init__`` stays a pure re-export facade. Type-checkers see the real symbols
(authlib assumed present); the runtime fallback is invisible to them.
"""

from typing import TYPE_CHECKING, NoReturn

if TYPE_CHECKING:
    from .oidc_auth import OIDCAuth, get_oauth
else:
    try:
        from .oidc_auth import OIDCAuth, get_oauth
    except ModuleNotFoundError as exc:
        _missing_authlib = exc

        def _requires_authlib(name):
            def _raise(*_args, **_kwargs) -> NoReturn:
                msg = (
                    f"{name} requires authlib. "
                    "Install it with: pip install dash-auth-async[oidc]"
                )
                raise ImportError(msg) from _missing_authlib

            _raise.__name__ = name
            return _raise

        OIDCAuth = _requires_authlib("OIDCAuth")
        get_oauth = _requires_authlib("get_oauth")

__all__ = ["OIDCAuth", "get_oauth"]
