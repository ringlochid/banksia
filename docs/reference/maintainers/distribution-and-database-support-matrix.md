# Distribution and database support matrix

| Surface | Shipped support |
| --- | --- |
| Python | 3.12 or newer |
| Artifacts | Wheel and source distribution from the root `pyproject.toml` |
| Default database | SQLite through `aiosqlite` |
| Optional database | PostgreSQL through the `postgres` extra and an explicit URL |
| Managed service | Linux `systemd --user` |
| Foreground service | `autoclaw serve` |
| Browser | Packaged same-origin console; real-backend Playwright proof is repository-only |

The repository editable install is a development path. A release must also pass an installed-wheel check outside the checkout.

Standalone binaries, npm wrappers, Homebrew packages, and native macOS or Windows service management are not shipped support.
