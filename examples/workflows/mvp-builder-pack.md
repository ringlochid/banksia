# MVP Builder Pack

Status: Reference

This is an example workflow-pack sketch, not an importable definition file. Importable workflow examples use the current authored YAML schema under `docs/reference/definitions/workflows/`.

Current-schema packs should keep authoring local to each object:

- workflow nodes use `description` for purpose and optional `instruction` for node-local prompt guidance
- roles use `instruction` for reusable role guidance
- policies use `instruction` for budget and capability behavior guidance
- task-compose uses `task.instruction` for task-local launch guidance

Useful lanes for an MVP build workflow:

- discovery
- architecture
- build
- validation
- launch/report
