# Testing and release checklist

- [ ] Code, docs, examples, and generated outputs agree.
- [ ] `make check-api` passes for backend changes.
- [ ] `make check-console` passes for console changes.
- [ ] `make check-docs` passes for maintained docs.
- [ ] Focused unit and integration tests cover the changed behavior.
- [ ] The applicable bounded, reviewed, or staged workflow lane passes.
- [ ] `make test-api-db` passes for schema, reset, or PostgreSQL changes.
- [ ] `make console-e2e-real` passes when browser behavior depends on a real backend.
- [ ] `make package-build` creates one wheel and one source distribution.
- [ ] Both artifacts were inspected for required and forbidden files.
- [ ] The wheel runs outside the checkout without `PYTHONPATH`.
- [ ] Packaged resources, FastAPI lifespan, foreground health/readiness, SQLite reset, provider setup/defaults, definition import, and task start were exercised from the installed wheel.
- [ ] The user-service installer and start/status/restart/stop/uninstall command sequence were proved in an isolated home.
- [ ] Skipped lanes have an exact scope reason.
