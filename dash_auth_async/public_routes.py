"""Public route and callback registration for unauthenticated access."""

import os
from typing import Any

from dash import Dash, callback, get_app

# The helpers Dash uses internally to key its callback map; no public API
# equivalent exists.
from dash._grouping import flatten_grouping  # noqa: PLC2701
from dash._utils import create_callback_id  # noqa: PLC2701
from dash.dependencies import Output, handle_grouped_callback_args
from werkzeug.routing import Map, MapAdapter, Rule

from .backends import detect_backend

DASH_PUBLIC_ASSETS_EXTENSIONS = "js,css"
BASE_PUBLIC_ROUTES = [
    f"/assets/<path:path>.{ext}"
    for ext in os.getenv(
        "DASH_PUBLIC_ASSETS_EXTENSIONS",
        DASH_PUBLIC_ASSETS_EXTENSIONS,
    ).split(",")
] + [
    "/_dash-component-suites/<path:path>",
    "/_dash-layout",
    "/_dash-dependencies",
    "/_favicon.ico",
    "/_reload-hash",
]
PUBLIC_ROUTES = "PUBLIC_ROUTES"
PUBLIC_CALLBACKS = "PUBLIC_CALLBACKS"


def callback_id(callback_args, callback_kwargs) -> tuple[Any, str]:
    """Derive the id Dash keys a callback under, exactly as ``register_callback``.

    Deterministic and independent of ``GLOBAL_CALLBACK_MAP`` state. Uses the
    grouped parser so flexible-signature (dict) outputs/inputs work too.

    Returns:
        ``(output, callback_id)``: the (possibly grouped) output spec and its id.
    """
    output, inputs, _state, _indices, _prevent = handle_grouped_callback_args(
        callback_args, callback_kwargs
    )
    flat_output = output if isinstance(output, Output) else flatten_grouping(output)
    return output, create_callback_id(flat_output, inputs, no_output=not flat_output)


def get_url_base(app: Dash) -> str:
    """Return the URL prefix configured for the Dash app (e.g. '/app/').

    Returns '' when no prefix is configured. Checks url_base_pathname first,
    then routes_pathname_prefix (the prefix the server actually routes on;
    requests_pathname_prefix is client-side and not read here).

    This reads from app.config at call time, so it must be invoked after the
    Dash app's URL config is fully initialised. In particular, calling
    add_public_routes() before url_base_pathname is set on the app will store
    routes without the prefix and they will never match at request time.
    """
    return (
        app.config.get("url_base_pathname")
        or app.config.get("routes_pathname_prefix")
        or ""
    )


def add_public_routes(app: Dash, routes: list):
    """Add routes to the public routes list.

    The routes passed should follow the Flask route syntax.
    e.g. "/login", "/user/<user_id>/public"

    Some routes are made public by default:
    * All dash scripts (_dash-dependencies, _dash-component-suites/**)
    * All dash mechanics routes (_dash-layout, _reload-hash)
    * All assets with extension .js or .css
      Note: you can modify the extensions by setting the
      `DASH_PUBLIC_ASSETS_EXTENSIONS` envvar before import (comma-separated
      list of extensions, e.g. "js,css,svg").
    * The favicon

    If you use callbacks on your public routes, you should use dash_auth_async's
    `public_callback` rather than the standard dash callback.

    :param app: Dash app
    :param routes: list of public routes to be added
    """
    public_routes = get_public_routes(app)
    url_base = get_url_base(app)

    if not public_routes.map._rules:
        routes = BASE_PUBLIC_ROUTES + routes

    for route in routes:
        full_route = route
        if url_base and not full_route.startswith(url_base):
            full_route = url_base.rstrip("/") + full_route
        public_routes.map.add(Rule(full_route))

    detect_backend(app.server).store_config(app.server, PUBLIC_ROUTES, public_routes)


def public_callback(*callback_args, **callback_kwargs):
    """Public Dash callback.

    This works by adding the callback id (from the callback map) to a list
    of whitelisted callbacks in the Flask server's config.

    :param **: all args and kwargs passed to a dash callback

    Returns:
        A decorator that registers the public Dash callback.
    """

    def decorator(func):
        wrapped_func = callback(*callback_args, **callback_kwargs)(func)
        # Derive the callback id straight from the output specs, exactly as
        # Dash does internally (create_callback_id). This is deterministic and
        # independent of GLOBAL_CALLBACK_MAP state -- unlike diffing the map,
        # which yields no new key when the same output id was already
        # registered (re-runs, or several apps sharing one process), and unlike
        # source-text comparison, which mis-whitelists callbacks sharing a body
        # and raises on lambdas/REPL-defined functions.
        _output, cb_id = callback_id(callback_args, callback_kwargs)
        try:
            app = get_app()
            backend = detect_backend(app.server)
            backend.store_config(
                app.server,
                PUBLIC_CALLBACKS,
                backend.read_config(app.server, PUBLIC_CALLBACKS, frozenset())
                | {cb_id},
            )
        except Exception:
            print(
                "Could not set up the public callback as the Dash object "
                "has not yet been instantiated."
            )

        # Return Dash's result as-is: a plain forwarding def would erase the
        # coroutine/generator kind of the user's function.
        return wrapped_func

    return decorator


def get_public_routes(app: Dash) -> MapAdapter:
    """Retrieve the public routes.

    Returns:
        The MapAdapter holding the app's registered public routes.
    """
    routes = detect_backend(app.server).read_config(app.server, PUBLIC_ROUTES)
    # Not a read_config default: that would build a Map on every request.
    return routes if routes is not None else Map([]).bind("")


def get_public_callbacks(app: Dash) -> frozenset[str]:
    """Retrieve the public callbacks ids.

    Returns:
        The set of whitelisted public callback ids (O(1) membership per request).
    """
    return detect_backend(app.server).read_config(
        app.server, PUBLIC_CALLBACKS, frozenset()
    )
