import pytest
import asyncio
from dash_auth_async import list_groups, check_groups

pytest.importorskip("quart", reason="Quart extra dependencies are not installed")


def test_gp004_list_groups_quart():
    from quart import Quart
    from quart import session as quart_session

    from dash_auth_async.backends import QuartBackend, set_active_backend

    app = Quart(__name__)
    app.secret_key = "Test!"

    async def run():
        async with app.test_request_context("/", method="GET"):
            quart_session["user"] = {"email": "a.b@mail.com", "groups": ["default"]}
            set_active_backend(QuartBackend())
            assert list_groups() == ["default"]
            assert check_groups(["default"]) is True
            assert check_groups(["other"]) is False

    asyncio.run(run())
