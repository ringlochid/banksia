# Bound workspace task-compose example

Use this example when the task should bind to a specific host path and create it if needed.

```yaml
task:
    key: host-bound-review
    title: Run a host-bound reviewed workflow
    summary: Bind the task workspace to an explicit host path.
    instruction: >-
      Run the reviewed-change workflow against a real host workspace and keep the task scoped to that path.
workflow:
    key: reviewed-change-release
roots:
    workspace:
        mode: ensure_host_path
        host_path: /home/ubuntu/workspaces/autoclaw-host-bound
```
