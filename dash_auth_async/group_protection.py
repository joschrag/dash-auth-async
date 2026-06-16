"""Group-based protection for Dash callbacks and outputs."""

import functools
import inspect
import logging
import re
from collections.abc import Callable
from typing import Any, Literal

import dash
from dash.exceptions import PreventUpdate

from .backends import get_active_backend
from .websocket_auth import _WS_AUTH_USER

OutputVal = Callable[[], Any] | Any
CheckType = Literal["one_of", "all_of", "none_of"]

# Sentinel: the gate authorises the call, so run the protected target rather
# than substitute a fallback output (a fallback may legitimately be None/falsy).
_PROCEED = object()


def _current_user() -> dict | None:
    """Resolve the authenticated user for the current dispatch.

    Single source of truth for "who is calling": under an HTTP request context
    this is the framework session user; on the WebSocket worker path (no
    framework context) it is the user the websocket_message hook stashed in
    ``_WS_AUTH_USER`` for this dispatch. Returns ``None`` when unauthenticated.

    Every helper that needs the caller -- ``list_groups`` and the default
    ``protected_callback`` fallbacks -- goes through here so none of them touch
    ``backend.session`` directly (which raises ``RuntimeError`` off-request).

    Returns:
        The authenticated user dict, or None when unauthenticated.
    """
    backend = get_active_backend()
    if backend.has_request_context():
        # Normal HTTP path: read the user from the framework session.
        return backend.session.get("user")
    # WebSocket worker path: no framework context here, so read the user the
    # websocket_message hook stashed for this dispatch.
    return _WS_AUTH_USER.get()


def list_groups(
    *,
    groups_key: str = "groups",
    groups_str_split: str | None = None,
) -> list[str] | None:
    """List all the groups the user belongs to.

    :param groups_key: Groups key in the user data saved in the backend session
        e.g. session["user"] == {"email": "a.b@mail.com", "groups": ["admin"]}
    :param groups_str_split: Used to split groups if provided as a string

    Returns:
        None if the user is not authenticated, otherwise the list of groups.
    """
    user = _current_user()
    if user is None:
        return None

    user_groups = user.get(groups_key, [])
    # Handle cases where groups are ,- or ;-separated string,
    # may depend on OIDC provider
    if isinstance(user_groups, str) and groups_str_split is not None:
        user_groups = re.split(groups_str_split, user_groups)
    return user_groups


def check_groups(
    groups: list[str] | None = None,
    *,
    groups_key: str = "groups",
    groups_str_split: str | None = None,
    check_type: CheckType = "one_of",
) -> bool | None:
    """Check whether the current user is authenticated and has the groups.

    :param groups: List of groups to check for with check_type
    :param groups_key: Groups key in the user data saved in the backend session
        e.g. session["user"] == {"email": "a.b@mail.com", "groups": ["admin"]}
    :param groups_str_split: Used to split groups if provided as a string
    :param check_type: Type of check to perform.
        Either "one_of", "all_of" or "none_of"

    Returns:
        None if the user is not authenticated; True if authenticated with the
        right permissions; False if authenticated without them.

    Raises:
        ValueError: if ``check_type`` is not a recognised value.
    """
    user_groups = list_groups(
        groups_key=groups_key,
        groups_str_split=groups_str_split,
    )

    if user_groups is None:
        # User is not authenticated
        return None

    if groups is None:
        return True

    if check_type == "one_of":
        return bool(set(user_groups).intersection(groups))
    if check_type == "all_of":
        return all(group in user_groups for group in groups)
    if check_type == "none_of":
        return not any(group in user_groups for group in groups)

    raise ValueError(f"Invalid check_type: {check_type}")


def protected(  # noqa: PLR0913 — public decorator with many optional knobs
    unauthenticated_output: OutputVal,
    *,
    missing_permissions_output: OutputVal | None = None,
    groups: list[str] | None = None,
    groups_key: str = "groups",
    groups_str_split: str | None = None,
    check_type: CheckType = "one_of",
) -> Callable:
    """Alter a function or output depending on authentication and permissions.

    :param unauthenticated_output: Output when the user is not authenticated.
        Note: needs to be a function with no argument or static outputs.
    :param missing_permissions_output: Output when the user is authenticated
        but does not have the right permissions.
        It defaults to unauthenticated_output when not set.
        Note: needs to be a function with no argument or static outputs.
    :param groups: List of authorized user groups. If no groups are passed,
        the decorator will only check whether the user is authenticated.
    :param groups_key: Groups key in the user data saved in the Flask session
        e.g. session["user"] == {"email": "a.b@mail.com", "groups": ["admin"]}
    :param groups_str_split: Used to split groups if provided as a string
    :param check_type: Type of check to perform.
        Either "one_of", "all_of" or "none_of"

    Returns:
        A decorator that wraps the target output with the auth gate.
    """
    if missing_permissions_output is None:
        missing_permissions_output = unauthenticated_output

    def decorator(output: OutputVal):
        def evaluate(value: OutputVal) -> Any:
            # Fallback outputs are documented as no-argument callables or
            # static values.
            return value() if isinstance(value, Callable) else value

        def gate() -> Any:
            """Return _PROCEED when authorised, else the fallback output."""
            authorized = check_groups(
                groups=groups,
                groups_key=groups_key,
                groups_str_split=groups_str_split,
                check_type=check_type,
            )
            if authorized is None:
                return evaluate(unauthenticated_output)
            if not authorized:
                return evaluate(missing_permissions_output)
            return _PROCEED

        # An async target must stay a coroutine function so Dash registers it on
        # its async dispatch path (dash _callback.py branches on
        # asyncio.iscoroutinefunction at registration). Wrapping it in a plain
        # def would erase that and the coroutine would never be awaited.
        if isinstance(output, Callable) and inspect.iscoroutinefunction(output):

            @functools.wraps(output)
            async def awrap(*args, **kwargs):
                fallback = gate()
                if fallback is _PROCEED:
                    return await output(*args, **kwargs)
                return fallback

            return awrap

        def wrap(*args, **kwargs):
            fallback = gate()
            if fallback is not _PROCEED:
                return fallback
            if isinstance(output, Callable):
                return output(*args, **kwargs)
            return output

        if isinstance(output, Callable):
            return wrap
        return wrap()

    return decorator


def _prevent_unauthenticated(func_name: str) -> None:
    """Default ``unauthenticated_output``: log and stop the callback.

    Raises:
        PreventUpdate: always, to stop the callback from running.
    """
    logging.info(
        "A user tried to run %s without being authenticated.",
        func_name,
    )
    raise PreventUpdate


def _prevent_unauthorised(func_name: str) -> None:
    """Default ``missing_permissions_output``: log and stop the callback.

    Resolves the caller via ``_current_user`` rather than touching
    ``backend.session`` directly, so it stays graceful on the WebSocket worker
    path (no request context) instead of raising ``RuntimeError``.

    Raises:
        PreventUpdate: always, to stop the callback from running.
    """
    user = _current_user() or {}
    logging.info(
        "%s tried to run %s but did not have the right permissions.",
        user.get("email", "<unknown user>"),
        func_name,
    )
    raise PreventUpdate


def protected_callback(  # noqa: PLR0913 — public decorator with many optional knobs
    *callback_args,
    unauthenticated_output: OutputVal | None = None,
    missing_permissions_output: OutputVal | None = None,
    groups: list[str] | None = None,
    groups_key: str = "groups",
    groups_str_split: str | None = None,
    check_type: CheckType = "one_of",
    **callback_kwargs,
) -> Callable:
    """Protected Dash callback.

    :param **: all args and kwargs passed to a Dash callback
    :param unauthenticated_output: Output when the user is not authenticated.
        **Note**: Needs to be a function with no argument or static outputs.
        You can access the Dash callback context within the function call if
        you need to use some of the inputs/states of the callback.
        If left as None, it will simply raise PreventUpdate, stopping the
        callback from processing.
    :param missing_permissions_output: Output when the user is authenticated
        but does not have the right permissions.
        It defaults to unauthenticated_output when not set.
        **Note**: Needs to be a function with no argument or static outputs.
        You can access the Dash callback context within the function call if
        you need to use some of the inputs/states of the callback.
        If left as None, it will simply raise PreventUpdate, stopping the
        callback from processing.
    :param groups: List of authorized user groups
    :param groups_key: Groups key in the user data saved in the backend session
        e.g. session["user"] == {"email": "a.b@mail.com", "groups": ["admin"]}
    :param groups_str_split: Used to split groups if provided as a string
    :param check_type: Type of check to perform.
        Either "one_of", "all_of" or "none_of"

    Returns:
        A decorator that registers the protected Dash callback.
    """

    def decorator(func):
        wrapped_func = dash.callback(*callback_args, **callback_kwargs)(
            protected(
                unauthenticated_output=(
                    unauthenticated_output
                    if unauthenticated_output is not None
                    else functools.partial(_prevent_unauthenticated, func.__name__)
                ),
                missing_permissions_output=(
                    missing_permissions_output
                    if missing_permissions_output is not None
                    else functools.partial(_prevent_unauthorised, func.__name__)
                ),
                groups=groups,
                groups_key=groups_key,
                groups_str_split=groups_str_split,
                check_type=check_type,
            )(func)
        )

        def wrap(*args, **kwargs):
            return wrapped_func(*args, **kwargs)

        return wrap

    return decorator
