# Packaged Starter Workflows

Status: Reference

Reviewed: 2026-07-22

These files define the small general-purpose Workflow set Banksia packages and bootstraps into an empty controller catalog. In product language they are **Starter Workflows**. “Seed” describes only their package/bootstrap role.

They are separate from the [maintained Workflow examples](../workflow-examples/README.md):

- reference examples teach the complete authoring language and may show provider, sandbox, network, model, effort, and capability configuration;
- packaged seeds are installed product inputs and therefore remain portable across installations;
- none of the reference examples is automatically seeded, published, or treated as package authority; and
- seed validation and reference-example validation are separate proof lanes.

## Portability rule

Every packaged seed must omit `provider` and `capabilities` at every Member. It therefore contains no provider kind, model, effort, sandbox/network request, Human Request grant, or Command Run grant. Provider resolution comes from the controller configuration for the installation, and optional capabilities are added later by a user who knows the local policy.

Seeds may use only the common Workflow fields: `kind`, `id`, `description`, `note`, `lead`, and Member `id`, `title`, `description`, `instruction`, and `children`. Their prose must remain domain-general and must not restate the Banksia system prompt, prescribe an executable stage sequence, or depend on OMC/OMX-specific commands, agents, phases, tools, or memory files.

## Seed set

1. [`reviewed-delivery.yaml`](reviewed-delivery.yaml) — an OMC Team-inspired maker plus independent reviewer under one accountable lead.
2. [`autonomous-delivery.yaml`](autonomous-delivery.yaml) — an OMX Autopilot-inspired intent, planning, delivery, and verification team without encoding a phase machine.
3. [`evidence-research.yaml`](evidence-research.yaml) — an OMX Best-Practice Research-inspired evidence, synthesis, and critical-review team.

The inspiration is structural, not product identity. User-facing seed IDs, titles, descriptions, and instructions are ordinary Banksia language and do not require users to know OMC or OMX.

## Bootstrap authority

Packaged YAML is a bootstrap input, never live runtime truth. Reset or first initialization validates each seed, creates its immutable published Workflow revision, and records package-owned provenance transactionally. Repeating the same bootstrap is idempotent by normalized content.

When a later Banksia package changes a package-owned seed, bootstrap may append and select a new package-owned immutable revision only while the Workflow's current revision is still package-owned. If a user-authored revision is current, the new packaged body may be retained in history but must not replace the user's current choice. Tasks continue to pin exact immutable revisions.
