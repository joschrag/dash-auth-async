import dash
import pytest
from flask import Flask, session

from dash_auth_async import check_groups, list_groups, protected, protected_callback


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
        # The split applies only to string groups; a list passes through as-is.
        assert list_groups(groups_str_split=",") == ["default"]


def test_gp_string_groups_without_split_are_one_group():
    # Review #5: a bare string used to reach `in`/set(), so "admin" matched
    # "superadmin" (substring) and one_of compared single characters.
    app = Flask(__name__)
    app.secret_key = "Test!"
    with app.test_request_context("/", method="GET"):
        session["user"] = {"email": "a.b@mail.com", "role": "superadmin"}
        assert list_groups(groups_key="role") == ["superadmin"]
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


def test_gp023_protected_gates_a_static_output():
    # A non-callable output is gated once, when protected() is applied.
    app = Flask(__name__)
    app.secret_key = "Test!"
    with app.test_request_context("/", method="GET"):
        session["user"] = {"email": "a.b@mail.com", "groups": ["default"]}
        allowed = protected(
            "anon", missing_permissions_output="forbidden", groups=["default"]
        )
        denied = protected(
            "anon", missing_permissions_output="forbidden", groups=["admin"]
        )
        assert allowed("static") == "static"
        assert denied("static") == "forbidden"


# The decorators must forward groups_key, groups_str_split and check_type to
# check_groups. Each assertion below flips if one of them is dropped: without
# groups_key the "role" claim isn't read (deny); without the split, "edit" is a
# substring of "admin,editor" (allow); without check_type, one_of is used.
ROLE_USER = {"email": "a.b@mail.com", "role": "admin,editor"}


def _protect_callback(monkeypatch):
    # Identity dash.callback: returns the gated function instead of
    # registering it, so it can be called directly.
    monkeypatch.setattr(dash, "callback", lambda *_a, **_k: lambda f: f)
    return protected_callback


@pytest.mark.parametrize(
    "get_decorator",
    [lambda _mp: protected, _protect_callback],
    ids=["protected", "protected_callback"],
)
def test_gp020_decorators_forward_group_options(get_decorator, monkeypatch):
    decorator = get_decorator(monkeypatch)
    app = Flask(__name__)
    app.secret_key = "Test!"

    def gate(groups, check_type="one_of"):
        return decorator(
            unauthenticated_output="unauthenticated",
            missing_permissions_output="forbidden",
            groups=groups,
            groups_key="role",
            groups_str_split=",",
            check_type=check_type,
        )(lambda: "success")

    with app.test_request_context("/", method="GET"):
        session["user"] = dict(ROLE_USER)
        assert gate(["editor"])() == "success"
        assert gate(["edit"])() == "forbidden"
        assert gate(["admin", "editor"], check_type="all_of")() == "success"
        assert gate(["admin", "other"], check_type="all_of")() == "forbidden"
        assert gate(["other"], check_type="none_of")() == "success"


def test_gp021_check_groups_forwards_group_options():
    app = Flask(__name__)
    app.secret_key = "Test!"
    with app.test_request_context("/", method="GET"):
        session["user"] = dict(ROLE_USER)
        assert check_groups(["editor"], groups_key="role", groups_str_split=",")
        assert not check_groups(["edit"], groups_key="role", groups_str_split=",")
