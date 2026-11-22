# Security policy

## Supported versions

| Version | Supported                                   |
|---------|---------------------------------------------|
| 2.x     | Yes                                         |
| 1.x     | Security fixes only, until 2027-05-22       |
| < 1.0   | No                                          |

1.x receives security fixes for six months after 2.0.0, for apps that cannot
upgrade yet (2.0 drops Python 3.10 and makes `authlib` an optional `oidc`
extra). See [Upgrading to 2.0](https://github.com/joschrag/dash-auth-async#upgrading-to-20)
in the README.

## Reporting a vulnerability

Report vulnerabilities privately through
[GitHub security advisories](https://github.com/joschrag/dash-auth-async/security/advisories/new),
not in public issues.
