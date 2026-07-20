# Run Docker-backed Postgres verification

This page defines the stronger DB-backed verification lane.

## Procedure

1. Run the self-contained DB-backed suite: `make test-api-db`

## What this proves

- Postgres-backed integration behavior
- the isolated Docker compose test path for Postgres-backed proof
- the stronger DB-backed verification lane used by the current repo tooling

## What this does not prove

- every provider or continuity scenario
- every local-only CLI path
- non-Postgres production environment behavior

## Relationship to the fast lane

This is the stronger current DB-backed lane.

Keep `make test-api-integration` as the default repo-native integration lane.

It is appropriate when you need:

- schema and reset proof on Postgres
- the Dockerized API test container path without depending on a separately-started compose stack
- higher-confidence runtime and registry verification than unit tests alone

## Notes

- `make test-api-db` brings up the isolated test compose project, recreates `autoclaw_test`, builds `infra/testing/api/Dockerfile`, runs the grouped integration suite, and tears the test project down on exit.
- The Dockerfile is test-only. It is not a shipped deployment image.
- `make docker-up` and `make docker-down` remain the manual development stack commands; they are not required for this proof lane.
