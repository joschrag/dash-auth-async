# Contributing

## Development

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then install the dev dependencies and run a single test:

```bash
uv sync --group dev --all-extras
uv run pytest -k ba001
```

User guides live in [`docs/`](docs/).

## Publishing

This package is available on PyPI. Releases are triggered automatically via GitHub Actions when a new version lands on `main`.

To publish a new release:

1. **PyPI Access**
   - Releases are published via [OIDC trusted publishing](https://docs.pypi.org/trusted-publishers/) — no API tokens or credentials are needed.
   - Request maintainer access by opening an issue or contacting the maintainer at 119843859+joschrag@users.noreply.github.com.

2. **Changelog and Version**
   - Add a new entry to `CHANGELOG.md` summarising the changes.
   - Bump the version with `uv version X.Y.Z` (updates `pyproject.toml`, the single source of truth). Follow [Semantic Versioning 2.0.0](https://semver.org/).
   - Create a PR, get it reviewed, and merge into `main`.

3. **Let CI tag and publish**
   Merging into `main` triggers the release workflow. If the version in `pyproject.toml` has no matching git tag yet,
   the workflow creates the `vX.Y.Z` tag itself, builds the package with `uv build`, and publishes it to PyPI.
   Don't push the tag manually.

4. **Verify**
   Once the workflow completes, confirm the release at https://pypi.org/project/dash-auth-async/.
