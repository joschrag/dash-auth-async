"""Differential tests: dash_auth_async must behave like upstream dash_auth.

Hypothesis drives both libraries with the same inputs on the Flask backend
(upstream is Flask-only) and asserts identical results. The only sanctioned
divergence is fail-closed handling: where upstream crashes with a 500 on a
malformed request, the fork must answer 401 instead.
"""

import base64
import contextvars
import json

import dash
import dash_auth as upstream
import pytest
from flask import Flask, session
from hypothesis import HealthCheck, given, settings, strategies as st

import dash_auth_async as fork
from dash_auth_async.public_routes import get_public_routes as fork_get_public_routes

pytestmark = pytest.mark.usefixtures("reset_active_backend")

SETTINGS = settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)

# Tiny alphabets so generated groups/paths collide often enough to hit the
# interesting branches (overlap, all-of, public-route matches).
group = st.one_of(
    st.sampled_from(["admin", "user", "dev"]),
    st.sampled_from(["a,b", "x;y", ""]),
)
groups_value = st.one_of(
    st.lists(group, max_size=4),
    st.lists(group, max_size=4),
    st.text(alphabet="ab,; ", max_size=8),
)
user_strategy = st.one_of(
    st.none(),
    st.fixed_dictionaries(
        {"email": st.just("u@x.io")},
        optional={"groups": groups_value, "tenant": groups_value},
    ),
)
groups_key = st.sampled_from(["groups", "tenant", "missing"])
groups_str_split = st.sampled_from([None, ",", ";", "[,;]", r"\s*,\s*"])
check_type = st.sampled_from(["one_of", "all_of", "none_of", "bogus"])
groups_arg = st.one_of(st.none(), st.lists(group, min_size=1, max_size=3))


def outcome(fn, *args, **kwargs):
    """Return a comparable result: the value, or the raised exception type."""
    try:
        return ("ok", fn(*args, **kwargs))
    except Exception as exc:
        return ("raise", type(exc))


def in_session(user, fn, *args, **kwargs):
    server = Flask(__name__)
    server.secret_key = "parity"
    with server.test_request_context("/"):
        if user is not None:
            session["user"] = user
        return outcome(fn, *args, **kwargs)


@SETTINGS
@given(user=user_strategy, key=groups_key, split=groups_str_split)
def test_parity_list_groups(user, key, split):
    kwargs = {"groups_key": key, "groups_str_split": split}
    assert in_session(user, fork.list_groups, **kwargs) == in_session(
        user, upstream.list_groups, **kwargs
    )


@SETTINGS
@given(
    user=user_strategy,
    groups=groups_arg,
    key=groups_key,
    split=groups_str_split,
    ctype=check_type,
)
def test_parity_check_groups(user, groups, key, split, ctype):
    kwargs = {
        "groups": groups,
        "groups_key": key,
        "groups_str_split": split,
        "check_type": ctype,
    }
    assert in_session(user, fork.check_groups, **kwargs) == in_session(
        user, upstream.check_groups, **kwargs
    )


@SETTINGS
@given(
    user=user_strategy,
    groups=groups_arg,
    ctype=check_type,
    missing=st.sampled_from([None, "forbidden", lambda: "forbidden-fn"]),
    target_is_func=st.booleans(),
    arg=st.integers(),
)
def test_parity_protected(user, groups, ctype, missing, target_is_func, arg):
    def run(lib):
        decorator = lib.protected(
            "unauthenticated",
            missing_permissions_output=missing,
            groups=groups,
            check_type=ctype,
        )
        target = (lambda x: ("ran", x)) if target_is_func else "static"
        wrapped = decorator(target)
        return wrapped(arg) if target_is_func else wrapped

    assert in_session(user, run, fork) == in_session(user, run, upstream)


# --- HTTP-level parity: BasicAuth + public routes behind a real Dash server ---

USERS = {"alice": "s3cret", "bob": "hunter2", "üser": "pässword"}
USER_GROUPS = {"alice": ["admin"], "bob": ["user", "dev"]}
PUBLIC = ["/home", "/user/<user_id>/public", "/files/<path:p>"]


def make_app(lib):
    app = dash.Dash(__name__)
    app.layout = dash.html.Div("parity")
    lib.BasicAuth(
        app,
        USERS,
        public_routes=list(PUBLIC),
        user_groups=USER_GROUPS,
        secret_key="parity",
    )
    return app


@pytest.fixture(scope="module")
def clients():
    return make_app(upstream).server, make_app(fork).server


def basic(user: str, password: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()


path = st.one_of(
    st.sampled_from(
        [
            "/",
            "/home",
            "/home/",
            "/secret",
            "/user/42/public",
            "/user/42/private",
            "/files/a/b.txt",
            "/_dash-layout",
            "/_dash-dependencies",
            "/_favicon.ico",
            "/assets/x.js",
            "/assets/x.png",
        ]
    ),
    st.text(alphabet="/abhomeuser42", min_size=1, max_size=15).map(
        lambda s: "/" + s.lstrip("/")
    ),
)
# Headers can't carry control characters (werkzeug rejects them client-side).
header_chars = st.characters(codec="latin-1", exclude_categories=["Cc"])
header = st.one_of(
    st.none(),
    st.sampled_from(list(USERS.items())).map(lambda up: basic(*up)),
    st.tuples(
        st.sampled_from([*USERS, "mallory"]), st.text(header_chars, max_size=8)
    ).map(lambda up: basic(*up)),
    st.text(header_chars, max_size=20),
    st.binary(max_size=12).map(lambda b: "Basic " + base64.b64encode(b).decode()),
)


VALID_HEADERS = {basic(u, p) for u, p in USERS.items()}


def assert_equivalent(up_resp, fork_resp, auth):
    if up_resp.status_code == 500 and auth not in VALID_HEADERS:
        # Sanctioned divergence: upstream's auth hook crashes on malformed
        # input, the fork fails closed instead.
        assert fork_resp.status_code == 401
    elif up_resp.status_code == 500:
        # Valid creds: the fork passes auth, so Dash itself may still 500 on
        # the malformed body -- but it must never succeed where upstream didn't.
        assert fork_resp.status_code in {401, 500}
    else:
        assert fork_resp.status_code == up_resp.status_code


def session_user(client):
    with client.session_transaction() as s:
        return s.get("user")


def _send(server, method, url, auth, **kwargs):
    client = server.test_client()
    headers = {} if auth is None else {"Authorization": auth}
    resp = client.open(url, method=method, headers=headers, **kwargs)
    return resp, session_user(client)


def send(server, method, url, auth, **kwargs):
    # Dash sets its app_context contextvar per request and never resets it;
    # isolate it so later get_app() calls (public_callback) don't see our apps.
    return contextvars.copy_context().run(_send, server, method, url, auth, **kwargs)


@SETTINGS
@given(url=path, auth=header)
def test_parity_basic_auth_http(clients, url, auth):
    up_server, fork_server = clients
    up_resp, up_user = send(up_server, "GET", url, auth)
    fork_resp, fork_user = send(fork_server, "GET", url, auth)
    assert_equivalent(up_resp, fork_resp, auth)
    if up_resp.status_code != 500:
        assert fork_user == up_user


pathname_input = st.fixed_dictionaries(
    {
        "id": st.just("url"),
        "property": st.just("pathname"),
        "value": st.one_of(st.none(), path),
    }
)
callback_body = st.one_of(
    st.fixed_dictionaries(
        {
            "output": st.sampled_from(["out.children", "nope.children"]),
            "outputs": st.just({"id": "out", "property": "children"}),
            "inputs": st.lists(
                st.one_of(
                    pathname_input,
                    st.just({"id": "x", "property": "value", "value": 1}),
                ),
                max_size=2,
            ),
            "changedPropIds": st.just([]),
        }
    ),
    # Malformed bodies: upstream 500s on these, the fork must 401.
    st.one_of(st.just({}), st.just([]), st.just({"output": "x"})),
)


@SETTINGS
@given(body=callback_body, auth=header)
def test_parity_callback_route(clients, body, auth):
    up_server, fork_server = clients
    data = json.dumps(body)
    kwargs = {"data": data, "content_type": "application/json"}
    up_resp, _ = send(up_server, "POST", "/_dash-update-component", auth, **kwargs)
    fork_resp, _ = send(fork_server, "POST", "/_dash-update-component", auth, **kwargs)
    assert_equivalent(up_resp, fork_resp, auth)


@SETTINGS
@given(
    routes=st.lists(
        st.sampled_from(["/a", "/a/<x>", "/b/<path:p>", "/c/<int:n>", "/home"]),
        max_size=4,
    ),
    probe=path,
)
def test_parity_add_public_routes(routes, probe):
    up_app, fork_app = dash.Dash(__name__), dash.Dash(__name__)
    upstream.add_public_routes(up_app, list(routes))
    fork.add_public_routes(fork_app, list(routes))
    up_map = up_app.server.config[upstream.public_routes.PUBLIC_ROUTES]
    assert fork_get_public_routes(fork_app).test(probe) == up_map.test(probe)


def test_parity_public_api_surface():
    """Every upstream export exists in the fork (drop-in replacement)."""
    missing = set(upstream.__all__) - set(fork.__all__)
    assert not missing
