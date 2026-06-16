"""Unit tests regarding protected sync and async callbacks."""

import asyncio
import inspect

from dash import Input, Output
from dash._callback import GLOBAL_CALLBACK_MAP
from flask import Flask, session

from dash_auth_async import protected, protected_callback

AUTHORIZED_SESSION = {"email": "a.b@mail.com", "groups": ["default"]}


# --------------------------------------------------------------------------- #
# Level 1: protected() preserves the coroutine contract
# --------------------------------------------------------------------------- #
def test_gp005_protected_keeps_sync_target_sync():
    """CONTROL: wrapping a sync target yields a plain (non-coroutine) callable."""

    def func():
        return "success"

    wrapped = protected(unauthenticated_output="unauth", groups=["default"])(func)

    assert not inspect.iscoroutinefunction(wrapped)


def test_gp006_protected_keeps_async_target_async():
    """RED: wrapping an async target must yield a coroutine function.

    Fails today: ``protected`` returns a synchronous ``def wrap`` regardless of
    the target, so Dash registers it on the sync dispatch path.
    """

    async def func():
        return "success"

    wrapped = protected(unauthenticated_output="unauth", groups=["default"])(func)

    assert inspect.iscoroutinefunction(wrapped)


# --------------------------------------------------------------------------- #
# Level 2: behaviour (auth gating) is preserved once async is honoured
# --------------------------------------------------------------------------- #
def test_gp007_async_protected_returns_inner_value_when_authorized():
    """RED-spec: an authorized async target's value survives the wrapper."""

    async def func():
        return "success"

    app = Flask(__name__)
    app.secret_key = "Test!"
    with app.test_request_context("/", method="GET"):
        session["user"] = dict(AUTHORIZED_SESSION)
        wrapped = protected(unauthenticated_output="unauth", groups=["default"])(func)

        assert inspect.iscoroutinefunction(wrapped)
        assert asyncio.run(wrapped()) == "success"


def test_gp008_async_protected_emits_missing_permissions_output():
    """RED-spec: an authenticated user lacking the group gets the forbidden output."""

    async def func():
        return "success"

    app = Flask(__name__)
    app.secret_key = "Test!"
    with app.test_request_context("/", method="GET"):
        session["user"] = dict(AUTHORIZED_SESSION)
        wrapped = protected(
            unauthenticated_output="unauth",
            missing_permissions_output="forbidden",
            groups=["admin"],
        )(func)

        assert inspect.iscoroutinefunction(wrapped)
        assert asyncio.run(wrapped()) == "forbidden"


# --------------------------------------------------------------------------- #
# Level 3: protected_callback registers on the correct Dash dispatch path
# --------------------------------------------------------------------------- #
def _register_and_get_dispatch(decorate, target):
    """Apply ``decorate`` to ``target`` and return the callable Dash stored.

    Snapshots ``GLOBAL_CALLBACK_MAP`` so we read back exactly the entry this
    registration added (the map is process-global and other tests populate it).
    The stored callable is ``async_add_context`` or ``add_context`` -- whichever
    Dash chose from the target's coroutine flag.
    """
    before = set(GLOBAL_CALLBACK_MAP)
    decorate(target)
    new_ids = set(GLOBAL_CALLBACK_MAP) - before
    assert len(new_ids) == 1, f"expected exactly one new callback, got {len(new_ids)}"
    return GLOBAL_CALLBACK_MAP[new_ids.pop()]["callback"]


def test_gp009_protected_callback_registers_sync_dispatch_for_sync_target():
    """CONTROL: a sync target lands on Dash's synchronous dispatch path."""

    def decorate(func):
        return protected_callback(
            Output("gp009-out", "children"),
            Input("gp009-in", "n_clicks"),
            prevent_initial_call=True,
        )(func)

    def target(_n_clicks):
        return "ok"

    dispatch = _register_and_get_dispatch(decorate, target)

    assert not inspect.iscoroutinefunction(dispatch)


def test_gp010_protected_callback_registers_async_dispatch_for_async_target():
    """RED: an async target must land on Dash's async dispatch path.

    Fails today: ``protected_callback`` hands Dash a sync wrapper, so Dash stores
    ``add_context`` and the coroutine is never awaited over the WebSocket.
    """

    def decorate(func):
        return protected_callback(
            Output("gp010-out", "children"),
            Input("gp010-in", "n_clicks"),
            prevent_initial_call=True,
        )(func)

    async def target(_n_clicks):
        return "ok"

    dispatch = _register_and_get_dispatch(decorate, target)

    assert inspect.iscoroutinefunction(dispatch)
