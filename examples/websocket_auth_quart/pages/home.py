"""Public landing page for the WebSocket + auth example."""

from dash import html, register_page

register_page(__name__, path="/", name="Home")

layout = html.Div(
    [
        html.H1("Quart + WebSockets + dash-auth-async"),
        html.P(
            "This example runs on the Dash Quart backend with WebSocket "
            "streaming callbacks, and demonstrates public vs authenticated "
            "pages using dash-auth-async BasicAuth."
        ),
        html.Ul(
            [
                html.Li("'/live' is public — anyone can watch the live counter."),
                html.Li("'/private' requires login (try admin / admin)."),
            ]
        ),
    ],
    style={"padding": "1rem"},
)
