# Run and operate work

A run starts one published Workflow revision with one complete prompt, one workspace, and optional file references. The Console keeps ordinary operation semantic: who owns the work, what changed, what needs you, and what the team finally returned.

## Start with one complete prompt

Open **Runs → New run**, choose a published Workflow, and state:

- the outcome the team must produce;
- relevant local context;
- constraints and compatibility boundaries;
- the proof expected before completion; and
- the form and location of any detailed deliverable.

Use **Advanced** to override the configured workspace or add existing workspace-relative file references. A reference is a path plus an optional description. Banksia records the reference, not a snapshot of the bytes.

The terminal starts the same product operation:

```bash
banksia task start
```

For automation, pass strict JSON inline, from `@file`, or through standard input:

```bash
banksia task start --json \
  '{"workflow":"debug-and-verify","prompt":"Reproduce the intermittent import failure, compare competing causes, implement only an evidence-supported repair, independently verify the original and adjacent cases, and return the result with referenced proof."}'
```

The controller must already be running. CLI-started runs use the invocation directory as their workspace.

## Read the run

Use `http://127.0.0.1:18125/runs` to find current and previous work. A run page answers five ordinary questions:

1. **Status:** is the work starting, active, waiting, paused, completed, blocked, or cancelled?
2. **Team:** which responsibility owns the current work?
3. **Current plan:** how is the team adapting its work now?
4. **Activity:** which meaningful update could change your understanding or next action?
5. **Result:** what exact outcome did the lead accept?

Banksia keeps raw attempts, dispatches, revisions, route facts, and event records out of this main story. Use support/audit surfaces only when diagnosing a specific problem.

## Respond when the team needs you

Human Requests are disabled unless the Workflow explicitly grants a Member one or more request kinds. After a grant, **Needs your attention** can present a typed request such as:

> **Which compatibility boundary should the repair preserve?**
>
> - Current public behavior — reject any user-visible change.
> - Current schema only — allow a documented behavior correction.
> - Something else — enter the exact boundary.

Read all questions and referenced files, then submit one response. Banksia records the response before making a continuation eligible. Receipt of the answer does not by itself mean the waiting work has resumed or finished.

A Command Run is also disabled unless the responsible Member has `command_run: allow`. When granted, the **Actions** section can show a purpose-led action such as **Run complete backend verification**, its managed state, bounded output, outcome, and a cancellation control when cancellation is currently legal.

An Action is not a per-command approval prompt. Ordinary provider commands are not automatically promoted into Action cards.

## Pause, resume, or cancel

Use only the controls shown on the current run:

- **Pause** prevents new provider work from starting; already completed history stays intact.
- **Resume** makes eligible continuation work start again.
- **Cancel** closes live work and external waits without rewriting earlier blocked or failed history into success.

Controls are current-state operations. Refresh and use the newly offered action if another operator or runtime event changed the run first.

## Recover after interruption

Controller records survive a provider process interruption or Banksia restart. On startup, Banksia audits durable state and converges work that can legally continue. Refresh the run to read current truth before taking another action.

This is local recovery, not distributed failover or blind replay. A provider's terminal success also does not prove assignment or run success; the controller must accept the corresponding state transition.

If the product view cannot explain the state, use the read-only [support endpoints](../reference/http-api.md) and [troubleshooting guide](../help/troubleshooting.md) for bounded diagnosis. Support state remains subordinate to controller truth.

## Read the Result and its files

The Result is the lead's exact final `green` or `blocked` Checkpoint. Read its summary and details before drawing a conclusion. A `blocked` Result is a valid, explicit outcome; it is not provider failure rewritten as success.

Result file references point to the shared workspace. Open those paths for detailed reports, changes, evidence, or review. The file may be missing or may have changed since the reference was recorded, so treat current bytes as loose workspace state rather than preserved Result content.
