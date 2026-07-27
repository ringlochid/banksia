# Use the Console and Operator

The Console and Operator are separate ways to act on the same controller-owned product truth. Use the Console for direct visual control. Use the Operator to translate ordinary language into the same bounded Workflow and run operations.

## Console

From a prepared source checkout, stage the visual Console and start Banksia:

```bash
make console-package-assets
./.venv/bin/banksia serve
```

Open `http://127.0.0.1:18125/`. The current routes are:

- `/workflows` — search the library, distinguish Starters and drafts, and create a Workflow;
- `/workflows/{workflow-id}` — inspect, edit, validate, undo, discard, or publish a draft using its current legal actions;
- `/runs` — search current and previous work;
- `/runs/new` — choose a published team, enter a complete prompt, and add optional workspace and file references; and
- `/runs/{task-id}` — read Status, Result, Team, Current plan, Activity, attention, Actions, and current run controls.

The Console is functional, temporary, and currently desktop-oriented. A mature visual redesign, mobile and tablet experiences, and broader accessibility polish are deferred rather than part of the current interface.

## Operator

The Operator is a separate control-plane agent configured with Codex or Claude. It is not a Task Member and does not join a run's team.

Its exact product-operation boundary lets it:

- search Workflows, read catalog or revision detail, and inspect authoring options;
- create, edit, validate, undo, discard, and publish Workflow drafts;
- search runs, read overview, Member, Result, Activity, or Human Request views, start a run, and invoke a currently legal pause, resume, or cancel action;
- answer or cancel an open Human Request using its current action; and
- inspect a Command Run, read bounded output, or request cancellation using its current action.

The Operator has no generic filesystem or file-content operations, shell, network, provider setup, external MCP, support/audit, runtime delegation, Checkpoint, or Task-member context authority. Its links and file references come from product readbacks; they do not grant another read path.

“Create a Workflow” authorizes a draft, not publication or a run. Mutations use controller currentness and accepted receipts. When a later claim depends on the change, the Operator rereads current product truth.

## Typed clarification is a two-turn flow

When a material choice is missing, the Operator returns native `ask_user` output instead of guessing:

1. The provider returns one to three typed questions and ends that turn.
2. Each question has two or three stable options. The Console supplies **Something else**, and shows skip only when the question explicitly allows it.
3. You answer every current question and choose **Continue**.
4. Banksia persists the answers, starts a fresh provider turn in the same conversation thread, and rereads controller truth before continuing.

The provider is not suspended inside an open tool call while you answer. Operator clarification is also separate from a Task Member's Human Request; the two surfaces have different owners and capabilities.

When no clarification is needed, the Operator returns one human-facing message with product links or file references from its accepted readbacks.

## Configure the Operator

Guided `banksia init` offers Operator as an optional final choice. Configure or change it later with:

```bash
banksia operator setup
banksia operator status
```

Choose Codex or Claude. The saved provider is the default when you rerun setup. Model and effort overrides are optional and remain unchanged when you decline to edit them; enter `-` during editing to restore a provider default. If the selected managed route is not configured, the interactive flow uses the same provider setup path as Task providers. An unchanged selection asks before running the provider diagnostic. A failure reports that the route needs attention without removing the saved Operator choice.

Automation supplies the selection explicitly:

```bash
banksia operator setup \
  --provider codex \
  --non-interactive
```

Remove only the saved Operator selection with:

```bash
banksia operator disable
```

Disabling Operator does not disable its provider route or change the default Task provider. An effective `BANKSIA_OPERATOR__*` environment override remains in effect until you remove that override.

Operator conversations use same-origin local HTTP routes. They do not expose an external MCP server or make Operator operations available to Workflow Members.
