import dash
from flask import Flask, session

from dash_auth_async import check_groups, list_groups, protected


def test_gp001_list_groups():
    app = Flask(__name__)
    app.secret_key = "Test!"
    with app.test_request_context("/", method="GET"):
        session["user"] = {
            "email": "a.b@mail.com",
            "groups": ["default"],
            "tenant": "ABC",
        }
        assert list_groups() == ["default"]
        assert list_groups(groups_key="tenant", groups_str_split=",") == ["ABC"]


def test_gp_string_groups_without_split_are_one_group():
    # Review #5: a bare string used to reach `in`/set(), so "admin" matched
    # "superadmin" (substring) and one_of compared single characters.
    app = Flask(__name__)
    app.secret_key = "Test!"
    with app.test_request_context("/", method="GET"):
        session["user"] = {"email": "a.b@mail.com", "role": "superadmin"}
        assert list_groups(groups_key="role") == "superadmin"  # unchanged in 1.x
        assert check_groups(["admin"], groups_key="role", check_type="all_of") is False
        assert check_groups(["s"], groups_key="role") is False
        assert check_groups(["admin"], groups_key="role", check_type="none_of") is True
        assert check_groups(["superadmin"], groups_key="role") is True


def test_gp002_check_groups():
    app = Flask(__name__)
    app.secret_key = "Test!"
    with app.test_request_context("/", method="GET"):
        session["user"] = {
            "email": "a.b@mail.com",
            "groups": ["default"],
            "tenant": "ABC",
        }
        assert check_groups(["default"]) is True
        assert check_groups(["other"]) is False
        assert check_groups(["default", "other"]) is True
        assert check_groups(["other", "default"], check_type="all_of") is False
        assert check_groups(["default"], check_type="all_of") is True
        assert check_groups(["other", "default"], check_type="none_of") is False
        assert check_groups(["other"], check_type="none_of") is True


def test_gp003_protected():
    app = Flask(__name__)
    app.secret_key = "Test!"

    def func():
        return "success"

    with app.test_request_context("/", method="GET"):
        session["user"] = {
            "email": "a.b@mail.com",
            "groups": ["default"],
            "tenant": "ABC",
        }
        f0 = protected(
            unauthenticated_output="unauthenticated",
            missing_permissions_output="forbidden",
            groups=["default"],
        )(func)
        assert f0() == "success"

        f1 = protected(
            unauthenticated_output="unauthenticated",
            missing_permissions_output="forbidden",
            groups=["admin"],
        )(func)
        assert f1() == "forbidden"

        del session["user"]
        assert f1() == "unauthenticated"


def test_gp022_background_kwargs_on_dash_without_mcp(monkeypatch):
    # Dash before MCP rejects an unknown mcp_enabled keyword, so on those
    # versions the background kwargs must pass through without it.
    from dash_auth_async.group_protection import _without_ungated_entry_points

    def callback_without_mcp(*_args, background=False, **_kwargs): ...

    monkeypatch.setattr(dash, "callback", callback_without_mcp)
    kwargs = {"background": True, "manager": None}
    assert _without_ungated_entry_points(kwargs) == kwargs
