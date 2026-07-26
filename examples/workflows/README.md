# Workflow catalog

Use these teams to upgrade ad-hoc subagent work into reusable responsibilities with explicit challenge and verification. Start with an installed Starter. Move to an advanced reference only when the work requires deliberate provider or access differences.

A Workflow tree describes who owns whose work, not when it happens. The running lead and Managers choose sequential, parallel, iterative, batch, or hybrid work from the prompt and current evidence.

## Installed Starters

`banksia init` publishes these seven provider- and capability-neutral Workflows. They use the installation's default provider and grant neither Human Request nor Command Run.

### Developer teams

| Starter | Responsibility tree | Challenge and verification boundary |
| --- | --- | --- |
| `reviewed-code-change` | Change lead → implementation manager → code owner and test owner; independent reviewer | Production edits, focused proof, finding disposition, and independent review remain separately owned. |
| `debug-and-verify` | Debug lead → investigation manager → reproducer and hypothesis challenger; repair owner; independent verifier | Reproduction, competing causes, correction, and verification cannot collapse into one plausible patch claim. |
| `cross-layer-feature` | Feature lead → contract owner; layer delivery manager → service and experience owners; integration verifier | Shared contract decisions, disjoint layer delivery, and end-to-end user proof stay visible. |
| `bounded-maintenance-batch` | Batch lead → inventory owner; batch manager → item worker and batch reviewer; integration verifier | A finite inventory, consistent item changes, systematic review, and integrated repository proof account for the whole batch. |

### Research and decision teams

| Starter | Responsibility tree | Challenge and verification boundary |
| --- | --- | --- |
| `evidence-synthesis` | Research lead → local evidence researcher, source researcher, and evidence critic | Local facts, external claims, inference, provenance, contradiction, and confidence remain distinguishable. |
| `reproducible-study` | Study lead → methods owner; study manager → execution and replication owners; claim auditor | Method, execution, independent replication, deviations, and claim limits remain separately accountable. |
| `technical-decision` | Decision lead → local fit analyst; option council → advocate and countercase analyst; decision reviewer | Every serious option faces the same local constraints, adversarial case, fair comparison, and revisit conditions. |

Choose by the proof the work needs, not just its topic. For example, use `debug-and-verify` when the cause itself is uncertain; use `reviewed-code-change` when the bounded change is understood but implementation and independent review must stay separate.

## Advanced references

These three YAML definitions are maintained schema and authoring references. They are not controller seeds, and their access choices may not fit your installation.

| Reference | Team and deliberate access boundary |
| --- | --- |
| [`advanced-reviewed-code-change.yaml`](advanced-reviewed-code-change.yaml) | Codex owns lead, management, and code responsibilities; Claude owns focused tests and read-only review. The lead can open Human Requests, and the implementation manager can create managed Command Runs. |
| [`advanced-cross-layer-delivery.yaml`](advanced-cross-layer-delivery.yaml) | Codex owns the lead, delivery manager, and service layer; Claude owns read-only contract and integration review plus the write-capable experience layer. Network and capability grants differ by responsibility. |
| [`advanced-technical-decision.yaml`](advanced-technical-decision.yaml) | Claude leads and challenges the decision, Codex inspects local fit read-only, and an externally configured OpenClaw route researches current upstream sources. Banksia does not configure or verify that external OpenClaw access. |

Inspect every provider, sandbox, network, and capability choice before import. Provider and capability settings apply only to the Member where they appear; children do not inherit them.

## Import an advanced reference

Import creates a controller-owned draft:

```bash
banksia workflow import --file \
  examples/workflows/advanced-reviewed-code-change.yaml
```

Open the draft in **Workflows**, validate it, and publish it explicitly before starting a run. Import does not publish or run the team.

YAML and JSON use the same closed [Workflow definition](../../docs/reference/workflows/README.md). Keep project-specific outcomes and constraints out of the reusable definition; put them in the run prompt.

Optional run file references remain separate too:

```json
{
  "workflow": "advanced-technical-decision",
  "prompt": "Compare the two migration approaches against this repository's accepted constraints, challenge the leading option, and return one reviewable decision with uncertainty and revisit conditions.",
  "files": [
    {
      "path": "docs/migration-constraints.md",
      "description": "Constraints accepted by the project"
    }
  ]
}
```

That file entry records a workspace-relative path and optional description, not preserved file content. The current file can later change or disappear.
