# Copied e2e workspace task-compose example

Use this example when you already copied a workspace for an isolated e2e run and the bound path must already exist.

```yaml
task:
    key: copied-e2e-run
    title: Run against a copied e2e workspace
    summary: Reuse an existing copied workspace.
    instruction: >-
      Launch the task against an already prepared copied workspace without creating new task-owned paths.
workflow:
    key: reviewed-change-release
roots:
    workspace:
        mode: use_existing_host
        host_path: /home/ubuntu/.e2e/sample-repos/runs/copied-repo
```
