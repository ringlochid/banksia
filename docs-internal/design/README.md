# Banksia design canon

Status: Target

This versionless tree is the authoritative target product and implementation contract for Banksia. It defines the destination of the preserve-first migration; it does not claim that the current AutoClaw 0.1.8 implementation already ships these contracts.

## Authority

For Banksia implementation questions, use this order:

1. the subject owner in this tree;
2. an exact appendix named by that owner;
3. an accepted ADR for durable rationale; and
4. frozen V1/V2 design or current pages only as migration and shipped-baseline evidence.

The versioned design trees and `current/v1` no longer own Banksia target behavior. Code and tests can reveal migration gaps, but they do not overrule this target. If this tree is silent on a material product decision, patch the owning subject page before implementation rather than inferring a new contract from legacy shape.

## Read in this order

1. [Product and Workflow](product-and-workflow.md) — product position, the one authored Workflow, Task start, Assignment, provider intent, and narrow built-in capability grants.
2. [Runtime](runtime.md) — responsibility, participation, replan, Checkpoints, Attempt-local waits, recursive Delegation Waves, and exact Results.
3. [Built-in runtime tools](runtime-tools.md) — exact Task-member and Operator operation inventories, schemas, exposure, and transfer semantics.
4. [Workspace, files, and prompt](workspace-files-and-prompt.md) — the shared native workspace, physical `.banksia/`, loose files, Command Run output, Dispatch requests, and prompt data boundary.
5. [Task member system prompts](system-prompts.md) — controller-owned prompt assets, accountable management, conditional action teaching, deterministic XML, and behavioral evaluations.
6. [Interfaces, Console, and Operator](interfaces-console-and-operator.md) — semantic product APIs and the nontechnical Workflow, Run, and Operator experience.
7. [Migration](migration.md) — preserve-first cutover, deletion gates, package ordering, final layout, and documentation contraction.
8. [Verification gates](verification-gates.md) — package evidence, race and failure matrices, usability proof, and the sole numeric owner of hidden controller validation guardrails.

Exact design fixtures and implementation-reference protocols live under the [appendices](appendices/README.md). Durable clean-break rationale lives in [ADR-0013](../adr/ADR-0013-banksia-target-and-clean-break.md).

## Target in brief

Banksia is an accountable, auditable, reproducible, and trackable form of ordinary subagent teamwork. A user publishes one recursive Workflow responsibility tree and starts a Task with one prompt. Managers decide and revise sequence, parallelism, iteration, batch work, and hybrid execution from evidence. The controller preserves exact authority, lineage, waits, joins, Checkpoints, file-reference values, and recovery while every Task member works through one shared native workspace. The ordinary product surface presents human work facts and one exact root Result; technical runtime truth remains a separate support and audit concern.

## Change rule

- Keep one owner for each normative contract. Cross-owner summaries must link back rather than fork the rule.
- Keep examples and packaged Starter Workflow seeds distinct. Reference examples demonstrate the complete authoring language; only the separate provider-neutral seed set is intended for bootstrap.
- Keep ignored research, screenshots, source-study clones, execution logs, and curation discussions out of tracked authority. Promote only the resolved contract or distilled protocol needed by implementation.
- Preserve a proven controller invariant until its target owner and direct replacement proof exist. A simpler public model is not permission to remove authority, currentness, recovery, or audit truth early.
- Do not restore rejected concepts through compatibility aliases, hidden readers, UI-only fields, prompts, fixtures, or examples.

## Frozen migration evidence

The [V1 design tree](v1/README.md), [V2 design tree](v2/README.md), and [shipped current tree](../current/v1/README.md) are frozen evidence for the AutoClaw baseline. Later work packages may use them to characterize or remove old behavior, but they are not alternate target canon and are not maintained as live Banksia owners.
