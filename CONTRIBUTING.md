# Contributing

## Publishing

This package is available on PyPI. Releases are triggered automatically via GitHub Actions when a version tag is pushed.

To publish a new release:

1. **PyPI Access**
   - Releases are published via [OIDC trusted publishing](https://docs.pypi.org/trusted-publishers/) — no API tokens or credentials are needed.
   - Request maintainer access by opening an issue or contacting the maintainer at 119843859+joschrag@users.noreply.github.com.

2. **Changelog and Version**
   - Add a new entry to `CHANGELOG.md` summarising the changes.
   - Bump the version in `pyproject.toml` and `dash_auth_async/version.py`. Follow [Semantic Versioning 2.0.0](https://semver.org/).
   - Create a PR, get it reviewed, and merge into `main`.

3. **Push a Git Tag**
   The tag must match the version in `pyproject.toml` exactly (e.g. `v1.0.0`).
   ```
   git tag -a 'v1.0.0' -m 'v1.0.0'
   git push origin main --follow-tags
   ```
   Pushing the tag triggers the release workflow, which builds the package with `uv build` and publishes it to PyPI automatically.

4. **Verify**
   Once the workflow completes, confirm the release at https://pypi.org/project/dash-auth-async/.
