# Workflow catalog

Use these teams when independent evidence, disjoint ownership, durable work, or
adversarial verification earns the coordination cost. Start with an installed
Starter. Use a one-Member Workflow when the work is small, tightly coupled, or
would make every teammate reread the same context.

A Workflow tree describes who owns whose work, not when it happens. The running lead and Managers choose sequential, parallel, iterative, batch, or hybrid work from the prompt and current evidence.

## Installed Starters

`oms init` publishes eight provider-neutral Workflows. Their descriptions
appear in the Workflow library, while this page supplies a sample mission and
the reason a team helps.

Every omitted capability denies. A few Members explicitly receive Human Request
for material user decisions or managed Command Run for long, supervised
processes. Capabilities never inherit. Inspect a Workflow before use.

### Daily complex work

#### Production feature delivery

Choose `production-feature-delivery` when a consequential feature crosses a
product or interface contract and more than one implementation boundary.

**Sample mission:** introduce an account-recovery journey spanning data, API,
and Console behavior while preserving existing clients, then prove the
integrated path and release readiness.

The contract owner establishes shared assumptions, the delivery Manager
reconciles service and experience ownership, and an independent integration
verifier can supervise long complete-system checks. The lead may request user
direction, approval, or review.

#### Incident investigation and recovery

Choose `incident-investigation-and-recovery` when the cause is uncertain, the
failure is intermittent or systemic, or recovery must remain distinct from the
person proposing the explanation.

**Sample mission:** determine why a scheduled import fails only under production
load, compare competing causes, implement the supported recovery, verify it
under the original conditions, and produce prevention actions.

Reproduction and hypothesis challenge remain independent. Recovery follows
evidence, not the first plausible patch; verification and prevention have
separate owners. The lead may request missing incident input or approval, while
reproduction and verification can supervise long-running checks.

#### Migration and modernisation

Choose `migration-and-modernisation` for a large framework, dependency, API,
repository, or codebase change with a finite inventory and real cutover risk.

**Sample mission:** migrate a repository from one authentication API to another,
update every consumer in dependency order, preserve supported compatibility,
remove stale paths, and prove the installed cutover.

Inventory precedes batch work. A reusable worker handles bounded items, a
consistency reviewer finds systematic drift, and independent stale-path and
cutover owners judge the complete repository rather than a reported item count.

#### Deep research and decision brief

Choose `deep-research-and-decision-brief` when a consequential decision depends
on broad local and external evidence whose provenance and contradictions must
survive review.

**Sample mission:** decide whether a new storage architecture fits the current
recovery contract, operational constraints, upstream support, and expected
workload.

Local facts, primary sources, counterevidence, and claim audit remain distinct.
The lead may request missing context or a material direction, then owns one
confidence-calibrated recommendation rather than concatenating research reports.

#### Decision through competing prototypes

Choose `decision-through-competing-prototypes` when prose comparison cannot
resolve a consequential product or technical choice.

**Sample mission:** implement two bounded search approaches against the same
representative corpus, evaluate quality, latency, operability, and migration
cost under one rubric, and select one with explicit revisit conditions.

Constraint ownership precedes independent candidate work. A common-rubric
evaluator may supervise long benchmarks, while a critic checks whether the
decision actually follows from comparable evidence.

### Ambitious flagship work

#### Idea to validated demo

Choose `idea-to-validated-demo` when a promising application or product idea
should become an evidence-backed position, coherent first product, runnable
demo, launch strategy, and credible pitch.

**Sample mission:** investigate an AI incident-review assistant for small
engineering teams, position it against current alternatives, scope and build the
core review journey, validate that journey, and prepare a launch and pitch
grounded in what the demo actually proves.

Discovery covers customer need, market alternatives, and skeptical evidence.
One strategy owner keeps positioning and scope coherent. The demo-delivery
Manager uses concrete evaluator findings for repeated repair of the promised
journey. The evaluator judges a credible first version—not production-grade
accessibility, scalability, performance, or hardening unless the run explicitly
requires them. Customer and investor/competitor critics challenge the integrated
proposition. The lead may ask for input, direction, or review.

#### Experiment and replication program

Choose `experiment-and-replication-program` for a substantial computational,
data, benchmark, model, or empirical study whose claims require an explicit
method and independent replication.

**Sample mission:** compare two retrieval strategies across representative
datasets, preserve environments and failures, independently reproduce the
results, analyse uncertainty, and publish a report whose claims do not exceed
the evidence.

Methods precede interpretation. Primary execution and replication remain
independent and may supervise long experiments. Analysis and claim audit remain
separate so a promising result cannot silently outrun failed or partial
replication.

#### Security audit and hardening

Choose `security-audit-and-hardening` when a consequential system needs more than
one undifferentiated security scan.

**Sample mission:** map a service's identity, data, dependency, and deployment
trust boundaries; audit them independently; validate exploitable findings;
remediate accepted risks; and re-test plausible bypasses.

Attack-surface mapping guides specialised application, supply-chain, and
configuration audits. A finding validator rejects unsupported tool output
before hardening, and an adversarial verifier rechecks the repaired system. The
lead may request missing authority, direction, or approval.

## Advanced references

These three YAML definitions are maintained schema and authoring references. They are not controller seeds, and their access choices may not fit your installation.

| Reference | Team and deliberate access boundary |
| --- | --- |
| [`advanced-reviewed-code-change.yaml`](advanced-reviewed-code-change.yaml) | Codex owns lead, management, and code responsibilities; Claude owns focused tests and read-only review. The lead can open Human Requests, and the implementation manager can create managed Command Runs. |
| [`advanced-cross-layer-delivery.yaml`](advanced-cross-layer-delivery.yaml) | Codex owns the lead, delivery manager, and service layer; Claude owns read-only contract and integration review plus the write-capable experience layer. Network and capability grants differ by responsibility. |
| [`advanced-technical-decision.yaml`](advanced-technical-decision.yaml) | Claude leads and challenges the decision while Codex separately inspects local fit and researches current primary sources under distinct read-only network boundaries. |

Inspect every provider, sandbox, network, and capability choice before import. Provider and capability settings apply only to the Member where they appear; children do not inherit them.

## Import an advanced reference

Import creates a controller-owned draft:

```bash
oms workflow import --file \
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
