"""Example: Dash + Quart backend with WebSocket streaming and public/private auth.

Run:
    python examples/websocket_auth_quart/app.py

Then open http://127.0.0.1:8050/ in a browser.

Credentials for the private page:
    admin / admin
    viewer / viewer123
"""

from dash import Dash, dcc, html, page_container

from dash_auth_async import BasicAuth

app = Dash(
    __name__,
    backend="quart",
    use_pages=True,
    websocket_callbacks=True,
    suppress_callback_exceptions=True,
)

app.layout = html.Div(
    [
        html.Div(
            [
                dcc.Link("Home", href="/"),
                dcc.Link("Live (public)", href="/live"),
                dcc.Link("Private", href="/private"),
            ],
            style={
                "display": "flex",
                "gap": "1rem",
                "background": "#eee",
                "padding": "0.5rem 1rem",
            },
        ),
        page_container,
    ],
    style={"display": "flex", "flexDirection": "column", "fontFamily": "sans-serif"},
)

BasicAuth(
    app,
    {"admin": "admin", "viewer": "viewer123"},
    secret_key="example-secret-not-for-production",
    public_routes=["/", "/live"],
)

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8050, debug=True)
