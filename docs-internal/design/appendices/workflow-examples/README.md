# Workflow examples

Status: Reference

Reviewed: 2026-07-22

These are readable product stories, not random schema fixtures. They translate useful OMC/OMX team structures into Banksia's one recursive responsibility tree. They do not copy those projects' runtime state machines, skills, phases, or tool schemas.

These files are documentation and validation references only. Banksia never automatically installs, seeds, publishes, or selects them. Their provider and capability blocks deliberately demonstrate optional advanced authoring and may not work on every installation. The separate [Starter Workflow fixtures](../workflow-seeds/README.md) own the general provider-neutral Workflows that ship with Banksia.

## Read order

1. [`minimal.yaml`](minimal.yaml) — smallest valid Workflow and default-deny capability example.
2. [`full.yaml`](full.yaml) — OMC Team-inspired scoped delivery, coordinated implementation, independent verification, and bounded repair.
3. [`omx-autopilot.yaml`](omx-autopilot.yaml) — OMX Autopilot-inspired intent, consensus planning, delivery, review, and adversarial QA.
4. [`omx-best-practice-research.yaml`](omx-best-practice-research.yaml) — OMX Best-Practice Research-inspired local/upstream evidence and critical synthesis.

The reference examples use `kind`, stable Workflow `id`, catalog `description`, shared `note`, recursive `lead`, and Member `id`, `title`, `description`, `instruction`, `provider`, `capabilities`, and `children`. Collectively they show Codex, Claude, externally configured OpenClaw, model/effort/sandbox/network, all four Human Request kinds, managed Command Run, and nested teams. A leaf may omit `children`; any Member may omit optional prose/provider/capabilities as the minimal example demonstrates.

## How OMC/OMX maps to Banksia

OMC Team documents a lead-owned delivery pipeline with planning, execution, verification, fix responsibilities, bounded repair loops, and durable handoff context. The Banksia example retains those specific responsibilities as a suggested reusable team. It does not encode stages or execution order.

OMX Autopilot combines clarification, consensus planning, durable implementation, independent review, and adversarial QA, returning to planning or rework when a gate is not clean. The Banksia example models the people and their team-specific relationships without authoring a phase machine.

OMX Best-Practice Research separates repository exploration, primary upstream research, synthesis, uncertainty, and a read-only implementation handoff. The Banksia example keeps that evidence boundary and adds an accountable lead and independent critic.

Sources inspected at pinned upstream commits:

- [OMC Team skill at `67dddfc`](https://github.com/Yeachan-Heo/oh-my-claudecode/blob/67dddfc05ff29900d8251dcec0ed9dee3c947ffa/skills/team/SKILL.md)
- [OMX Autopilot skill at `435d4a9`](https://github.com/Yeachan-Heo/oh-my-codex/blob/435d4a9cc982ffaf83fabbfbb8711ae6c178ffca/skills/autopilot/SKILL.md)
- [OMX Best-Practice Research skill at `435d4a9`](https://github.com/Yeachan-Heo/oh-my-codex/blob/435d4a9cc982ffaf83fabbfbb8711ae6c178ffca/skills/best-practice-research/SKILL.md)

## Capabilities authorize; system prompts teach

`capabilities` is a narrow Member configuration surface:

```yaml
capabilities:
  human_request: [input, direction, approval, review]
  command_run: allow
```

Omitted fields deny. Grants do not inherit to children, and controller policy may narrow them. These fields only determine which built-in operations may be exposed. The actual Human Request and Command Run are runtime actions whose typed requests, waits, results, and Continuations remain controller records.

General guidance does not belong in these examples. Statements such as “open a Human Request instead of guessing,” “use Command Run only for long processes,” “choose a Wave,” “do not relay a child Checkpoint,” and “write a note before a complex delegation” live in the [controller-owned system prompts](../../system-prompts.md). Workflow `note` and Member `instruction` below contain only team-specific suggestions.

Checkpoint, delegate, replan, generic file references, and provider-native tools are runtime behavior and are not authored fields. External MCP integration and Skills remain deferred.

## One illustrative run

A Task start remains separate from its Workflow definition:

```yaml
workflow: omx-autopilot-delivery
prompt: |
  Add passkey sign-in to the existing account flow without breaking password
  login. Preserve the current public API and prove upgrade behavior.
workspace: /work/acme-app
files:
  - path: docs/account-compatibility.md
    description: Existing compatibility promise that the team must honor.
```

The root Assignment contains that exact prompt and ordered file reference. The lead decides actual ordering, grouping, repetition, and replanning at runtime; none is parsed from `children`, `note`, or Member prose.
