# User-group-based permissions

`dash_auth_async` provides a convenient way to secure parts of your app based on user groups.

The following utilities are defined:
* `list_groups`: Returns the groups of the current user, or None if the user is not authenticated.
* `check_groups`: Checks the current user groups against the provided list of groups.
  Available group checks are `one_of`, `all_of` and `none_of`.
  The function returns None if the user is not authenticated.
* `protected`: A function decorator that modifies the output if the user is unauthenticated
  or missing group permission.
* `protected_callback`: A callback that only runs if the user is authenticated
  and with the right group permissions.

NOTE: user info is stored in the session so make sure you define a secret_key on the server
to use this feature.

If you wish to use this feature with BasicAuth, you will need to define the groups for individual
basicauth users:

```python
from dash_auth_async import BasicAuth

app = Dash(__name__)
USER_PWD = {
    "username": "password",
    "user2": "useSomethingMoreSecurePlease",
}
BasicAuth(
    app,
    USER_PWD,
    user_groups={"username": ["group1", "group2"], "user2": ["group2"]},
    secret_key="Test!",
)

# You can also use a function to get user groups
def check_user(username, password):
    if username == "user1" and password == "password":
        return True
    if username == "user2" and password == "useSomethingMoreSecurePlease":
        return True
    return False

def get_user_groups(user):
    if user == "user1":
        return ["group1", "group2"]
    elif user == "user2":
        return ["group2"]
    return []

BasicAuth(
    app,
    auth_func=check_user,
    user_groups=get_user_groups,
    secret_key="Test!",
)
```
