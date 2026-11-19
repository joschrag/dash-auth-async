"""Streaming (async-generator) callbacks through dash-auth-async decorators.

Dash 4.5 added streaming callbacks: it picks the streaming dispatch path at
registration via ``inspect.isasyncgenfunction``. These tests exercise Dash's own
streaming machinery, so they only run where it exists. The wrapper-level kind
checks (gp011-gp017 in ``test_protected_callback_async.py``) test our code alone
and run on every Dash version.
"""

import base64
import json
import uuid

import dash
import pytest
from dash import Dash, Input, Output, html
from dash._callback import GLOBAL_CALLBACK_MAP
from packaging.version import Version

from dash_auth_async import BasicAuth, protected_callback, public_callback

pytestmark = [
    pytest.mark.skipif(
        Version(dash.__version__) < Version("4.5.0"),
        reason="streaming callbacks need dash>=4.5.0",
    ),
    pytest.mark.usefixtures(
        "reset_active_backend", "isolated_callback_registry", "streams_not_shut_down"
    ),
]

USERS = {"admin": "admin", "guest": "guest"}


@pytest.fixture
def streams_not_shut_down():
    """Clear Dash's process-global stream shutdown flag.

    Any earlier test whose Quart/FastAPI app shut down set it (via
    ``shutdown_active_streams``); only a real server start clears it, which a
    Flask test client never does -- every stream would then end empty.
    """
    from dash._streaming import _shutdown

    _shutdown.clear()


def _ids():
    # Unique ids: callbacks register into Dash's process-global map.
    tag = uuid.uuid4().hex
    return f"btn-{tag}", f"out-{tag}"


def _register(decorator, btn, out, target, **kwargs):
    decorator(
        Output(out, "children"),
        Input(btn, "n_clicks"),
        prevent_initial_call=True,
        **kwargs,
    )(target)


async def _agen(_n):
    yield "chunk-1"
    yield "chunk-2"


@pytest.mark.parametrize(
    ("decorator", "kwargs"),
    [(public_callback, {}), (protected_callback, {"groups": ["admin"]})],
)
def test_st001_async_generator_registers_as_dash_stream(decorator, kwargs):
    """RED before fix: protected_callback registered a plain def, not a stream."""
    btn, out = _ids()
    Dash(__name__)  # public_callback needs an instantiated app
    _register(decorator, btn, out, _agen, **kwargs)
    assert GLOBAL_CALLBACK_MAP[f"{out}.children"].get("stream") is True


def test_st002_sync_generator_rejected_at_registration():
    """protected() keeps the sync-generator kind, so Dash's own error surfaces."""

    def gen(_n):
        yield "x"

    btn, out = _ids()
    with pytest.raises(dash.exceptions.StreamCallbackError):
        _register(protected_callback, btn, out, gen, groups=["admin"])


def _headers(user):
    token = base64.b64encode(f"{user}:{user}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _post_stream(user):
    """POST one stream request on Flask to a group-protected streaming callback.

    Returns:
        ``(response, output_id)``.
    """
    from dash import LocalSharedStorage  # dash>=4.5 only; module must import on older

    btn, out = _ids()
    app = Dash(__name__, shared_storage=LocalSharedStorage())
    BasicAuth(app, USERS, user_groups={"admin": ["admin"]}, secret_key="Test!")
    app.layout = html.Div([html.Button(id=btn), html.Div(id=out)])
    _register(
        protected_callback,
        btn,
        out,
        _agen,
        groups=["admin"],
        missing_permissions_output="forbidden",
    )

    client = app.server.test_client()
    client.get("/", headers=_headers(user))  # runs Dash's _setup_server
    resp = client.post(
        "/_dash-update-component",
        json={
            "output": f"{out}.children",
            "outputs": {"id": out, "property": "children"},
            "inputs": [{"id": btn, "property": "n_clicks", "value": 1}],
            "changedPropIds": [f"{btn}.n_clicks"],
            "state": [],
        },
        headers=_headers(user),
    )
    return resp, out


def test_st003_authorised_user_receives_every_chunk_over_http():
    """RED before fix: Flask consumes the stream off-request, so the in-generator
    gate saw no user and denied even admins."""
    resp, out = _post_stream("admin")

    assert resp.status_code == 200
    assert resp.mimetype == "application/x-ndjson"
    frames = [
        json.loads(line) for line in resp.get_data(as_text=True).splitlines() if line
    ]
    assert frames[-1] == {"done": True}
    assert [f["response"][out]["children"] for f in frames[:-1]] == [
        "chunk-1",
        "chunk-2",
    ]


def test_st004_denied_user_gets_fallback_without_starting_stream():
    """Gated at dispatch: a denied user gets a plain callback response, no stream."""
    resp, out = _post_stream("guest")

    assert resp.status_code == 200
    assert resp.mimetype == "application/json"
    assert resp.get_json() == {
        "multi": True,
        "response": {out: {"children": "forbidden"}},
    }


@pytest.mark.parametrize(
    ("ws_user", "expected"),
    [
        ({"groups": ["admin"]}, ["chunk-1", "chunk-2"]),
        ({"groups": ["guest"]}, ["forbidden"]),
    ],
)
def test_st005_stream_gated_in_generator_over_websocket(ws_user, expected):
    """Over WS the hook's user reaches the stream task, so the gate runs there."""
    import asyncio

    from dash._callback_context import context_value
    from dash._utils import AttributeDict

    from dash_auth_async.websocket_auth import _WS_AUTH_USER

    btn, out = _ids()
    app = Dash(__name__)
    BasicAuth(app, USERS, user_groups={"admin": ["admin"]}, secret_key="Test!")
    stream = protected_callback(
        Output(out, "children"),
        Input(btn, "n_clicks"),
        groups=["admin"],
        missing_permissions_output="forbidden",
        prevent_initial_call=True,
    )(_agen)

    async def drain():
        # What Dash's WS dispatch sets up around each stream step.
        context_value.set(AttributeDict(dash_websocket=object()))
        _WS_AUTH_USER.set(ws_user)
        return [chunk async for chunk in stream(1)]

    assert asyncio.run(drain()) == expected


def test_st006_stream_allowed_over_websocket():
    """Unlike background callbacks, streams may run over WS (gated in-generator)."""
    btn, out = _ids()
    app = Dash(__name__)
    auth = BasicAuth(app, USERS, user_groups={"admin": ["admin"]}, secret_key="Test!")
    _register(protected_callback, btn, out, _agen, groups=["admin"])
    assert auth.authorize_ws({"output": f"{out}.children"}, {"groups": []}) is True
