# Run and operate Tasks

A Task starts from one published Workflow, one required prompt, one workspace, and optional file references.

## Start interactively

Run:

```bash
banksia task start
```

The interactive path lists the available published Workflows and opens an editor for the Task prompt. CLI-started Tasks use the invocation directory as their workspace.

## Start from JSON

Automation uses one strict JSON object:

```bash
banksia task start --json \
  '{"workflow":"reviewed-delivery","prompt":"Review and improve the import error path."}'
```

Read from a file or standard input:

```bash
banksia task start --json @task.json
banksia task start --json - < task.json
```

The complete request shape is:

```json
{
  "workflow": "reviewed-delivery",
  "prompt": "Review and improve the import error path.",
  "workspace": "/absolute/path/to/project",
  "files": [
    {
      "path": "docs/accepted-constraints.md",
      "description": "Constraints accepted by the project"
    }
  ]
}
```

`workspace` is optional for HTTP, Console, and Operator starts when `paths.workspace` is configured. CLI start defaults to its invocation directory. Every file path must resolve to an existing regular file beneath the selected workspace.

## Follow the work

Open `http://127.0.0.1:18125/runs` or the Task detail route. The default activity view emphasizes facts that can change an operator's next action:

- lifecycle changes;
- teammate Checkpoints and the final Result;
- open and answered Human Requests; and
- Command Run start and terminal outcomes.

Dispatch IDs, attempts, revisions, route facts, and raw events remain available as technical detail rather than dominating the main progress story.

## Respond to waits

Human Requests appear as typed cards. Read the full question, select the stable option or enter an allowed free response, and submit once. Banksia records the answer before it resumes the waiting Attempt.

Command Runs appear with command, status, timestamps, and log path. The full streamed output is stored at:

```text
.banksia/t_<id>/command-runs/c_<id>/output.log
```

Use the Console or HTTP API to request cancellation. A cancellation request is durable; the terminal state is recorded after the controller has handled the process.

## Pause, resume, or cancel

Use the Task controls in the Console, Operator, or HTTP API. Pause prevents new provider work from starting; it does not rewrite completed history. Resume lets eligible continuations start. Cancel closes live work and external waits without turning earlier blocked history into success.

## Read the outcome

The lead's accepted terminal `green` or `blocked` Checkpoint is the exact user Result. Read its summary first, then open any referenced files for detailed plans, reports, reviews, or other deliverables.
