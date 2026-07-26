# Author a Workflow

A Workflow definition is a reusable team contract. Start from a packaged Starter, name responsibilities rather than phases, then validate and publish an immutable revision.

## Start in the Console

The fastest path is:

1. Open **Workflows** and choose the Starter closest to the work.
2. Open it for editing. Banksia creates or resumes a draft while the current published revision remains available for runs.
3. Give every Member one distinct responsibility and a clear boundary.
4. Validate the complete draft.
5. Publish only when the preview and validation findings match the intended team.

For example, `reviewed-code-change` separates a change lead, an implementation manager, code and test owners, and an independent reviewer. That separation is the product value: one Member does not silently implement, approve, and verify the same claim.

Connections in the team tree describe responsibility and delegation ownership, not time. Array order does not schedule work. At runtime, a Manager can choose sequential, parallel, iterative, batch, or hybrid assignments from the prompt and current evidence.

## Draft with the Operator

Ask the separate Operator for a team in ordinary language:

> Create a Workflow draft for a cross-layer feature. Keep the shared contract,
> service implementation, user experience, and integration verification under
> distinct ownership.

The Operator may ask a typed clarification, then create and edit the controller-owned draft. “Create a Workflow” authorizes drafting only. It does not authorize publication or starting a run.

The Operator has exact Workflow draft operations; it does not have generic file editing or filesystem authority. Review the resulting draft in the Console, validate it, and give an explicit publish instruction when it is ready.

## Write strong responsibilities

Use these tests for every Member:

- **Distinct:** another Member does not own the same decision or edit surface.
- **Necessary:** removing the responsibility would weaken the result.
- **Bounded:** the Member can tell what it owns and what it must return.
- **Reviewable:** another responsibility can challenge consequential claims without erasing ownership.

Keep the Workflow focused on reusable responsibility. Put the specific outcome, local constraints, and optional file references in the run prompt.

## Understand publication and currentness

Draft edits use controller-owned currentness checks so a stale browser or Operator turn cannot silently overwrite newer work. The Console handles these checks and offers current legal actions; reload before retrying a conflicted change.

Publishing creates an immutable Workflow revision and makes it current for new runs. It does not mutate older revisions or existing runs. Every Task pins the exact published revision selected at start. Later changes require a new draft and publication.

Validation proves the draft's current authoring rules. It is not publication and does not prove that a future provider route, Human Request, Command Run, or run start will be legal.

## Add advanced choices deliberately

The installed Starters omit providers and capabilities so they work with the installation default and deny privileged operations. Add advanced fields only when the responsibility requires them:

```yaml
provider:
    kind: codex
    model: gpt-5.6
    effort: high
    sandbox:
        mode: workspace_write
        network: deny
capabilities:
    human_request:
        - direction
        - approval
    command_run: allow
```

Provider and capability choices apply to that Member; children do not inherit them. Codex and Claude support managed model, effort, sandbox, and network choices. `openclaw` selects a user-operated route whose external access Banksia does not configure or verify.

Human Request kinds are `input`, `direction`, `approval`, and `review`. Command Run is a separate allow-or-deny capability. Both deny when omitted. Grant the smallest capability to the Member that owns the decision or managed command.

The three maintained advanced references make different boundaries explicit:

- [advanced reviewed code change](../../examples/workflows/advanced-reviewed-code-change.yaml);
- [advanced cross-layer delivery](../../examples/workflows/advanced-cross-layer-delivery.yaml); and
- [advanced technical decision](../../examples/workflows/advanced-technical-decision.yaml).

Review their exact provider and access assumptions in the [Workflow catalog](../../examples/workflows/README.md) before importing one.

## Use JSON or YAML when needed

The Console and Operator use the same closed Workflow model exposed by the public [definition reference](../reference/workflows/README.md) and [JSON Schema](../reference/workflows/workflow-definition.schema.yaml). YAML is convenient for maintained files; JSON is the structured HTTP and Operator shape.

Import a complete YAML or JSON definition as a draft:

```bash
banksia workflow import --file ./team.yaml
```

Standard input requires an explicit format:

```bash
banksia workflow import --file - --format json < team.json
```

Replacing an existing draft requires its current opaque ETag:

```bash
banksia workflow import --file ./team.yaml --etag '<current-etag>'
```

Import never publishes. Export the current published revision with:

```bash
banksia workflow export team-id --output ./team-id.yaml
```
