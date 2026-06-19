import asyncio
import inspect

import pytest

from dash_auth_async import check_groups, list_groups, protected

pytest.importorskip("quart", reason="Quart extra dependencies are not installed")


pytestmark = pytest.mark.usefixtures("reset_active_backend")


def test_gp004_list_groups_quart():
    from quart import Quart, session as quart_session

    from dash_auth_async.backends import QuartBackend, set_active_backend

    app = Quart(__name__)
    app.secret_key = "Test!"

    async def run():
        # quart annotates __aexit__ args without Optional, violating the
        # protocol on clean exit; works at runtime.
        async with app.test_request_context("/", method="GET"):  # ty: ignore[invalid-context-manager]
            quart_session["user"] = {"email": "a.b@mail.com", "groups": ["default"]}
            set_active_backend(QuartBackend())
            assert list_groups() == ["default"]
            assert check_groups(["default"]) is True
            assert check_groups(["other"]) is False

    asyncio.run(run())


def test_gp_async_protected_unauthenticated_without_session_user():
    """An async ``protected`` wrapper with no logged-in user short-circuits to
    ``unauthenticated_output`` over the Quart backend, while staying a coroutine
    so Dash keeps it on the async dispatch path.
    """
    from quart import Quart

    from dash_auth_async.backends import QuartBackend, set_active_backend

    app = Quart(__name__)
    app.secret_key = "Test!"

    async def func():
        return "success"

    async def run():
        async with app.test_request_context("/", method="GET"):  # ty: ignore[invalid-context-manager]
            # No session["user"] -> unauthenticated.
            set_active_backend(QuartBackend())
            wrapped = protected(
                unauthenticated_output="unauthenticated",
                missing_permissions_output="forbidden",
                groups=["admin"],
            )(func)

            assert inspect.iscoroutinefunction(wrapped)
            assert await wrapped() == "unauthenticated"

    asyncio.run(run())
