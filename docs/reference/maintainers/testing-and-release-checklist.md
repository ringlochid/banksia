# Testing and release checklist

- [ ] Code, docs, examples, and generated outputs agree.
- [ ] `make check-backend` passes for backend changes.
- [ ] `make check-console` passes for console changes.
- [ ] `make check-docs` passes for maintained docs.
- [ ] Focused unit and integration tests cover the changed behavior.
- [ ] The applicable bounded, reviewed, or staged workflow lane passes.
- [ ] `make test-backend-db` passes for schema, reset, or PostgreSQL changes.
- [ ] A clean `./.venv/bin/python -m build` creates one interim WP-09 wheel and one source distribution.
- [ ] Both artifacts were inspected for required and forbidden files.
- [ ] The wheel runs outside the checkout without `PYTHONPATH`.
- [ ] Packaged resources, FastAPI lifespan, foreground health/readiness, SQLite reset, provider setup/defaults, Workflow import, JSON Task start, and semantic Task readback after restart were exercised from the installed wheel.
- [ ] The user-service installer and start/status/restart/stop/uninstall command sequence were proved in an isolated home.
- [ ] Publication remains blocked until WP-10 supplies the root Console, browser proof, and one integrated release build.
- [ ] Skipped lanes have an exact scope reason.
