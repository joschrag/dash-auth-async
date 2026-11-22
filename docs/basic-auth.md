# Basic Authentication

To add basic authentication, add the following to your Dash app:

```python
from dash import Dash
from dash_auth_async import BasicAuth

app = Dash(__name__)
USER_PWD = {
    "username": "password",
    "user2": "useSomethingMoreSecurePlease",
}
BasicAuth(app, USER_PWD)
```

One can also use an authorization python function instead of a dictionary/list of usernames and passwords:

```python
from dash import Dash
from dash_auth_async import BasicAuth

def authorization_function(username, password):
    if (username == "hello") and (password == "world"):
        return True
    else:
        return False


app = Dash(__name__)
BasicAuth(app, auth_func = authorization_function)
```
