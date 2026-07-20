# Distribution and database support matrix

Status: Target

This page defines the frozen v1 support matrix.

## Shipped install path

- PyPI wheel/sdist
- `pipx install autoclaw`

## Shipped DB lanes

- SQLite local-first smoke lane
- Postgres package extra via `pipx install "autoclaw[postgres]"`

## Required strong verification lane

- Postgres + Docker
- `make docker-up`
- `make test-api-db`
- `make docker-down`

## Future or non-canonical lanes

- standalone binaries
- npm shim package
- Homebrew or other convenience installer
