# Pinned n8n interaction-reference protocol

Status: Reference

Pinned source-study facts:

- fetched 2026-07-22;
- upstream <https://github.com/n8n-io/n8n>;
- observed branch `master`; and
- commit [`43c6f329fb1fb528259a78f80b163e4ed1405c02`](https://github.com/n8n-io/n8n/commit/43c6f329fb1fb528259a78f80b163e4ed1405c02).

The ignored source-study clone lives at `tmp/codex/references/n8n-source/upstream/`. Its nested Git metadata keeps the exact upstream commit and selected paths inspectable. Do not update it silently: a later refresh must record a new commit, re-audit the license and selected files, update this map, and re-run the Banksia reference decisions. The exact non-cone selection is embedded in this tracked appendix. A local checkout copies it to the ignored `tmp/codex/references/n8n-source/sparse-paths.txt` before running the reconstruction commands.

To recreate the pinned snapshot when this ignored directory is absent:

```bash
git clone --depth 1 --filter=blob:none --no-checkout \
  https://github.com/n8n-io/n8n.git \
  tmp/codex/references/n8n-source/upstream
git -C tmp/codex/references/n8n-source/upstream fetch --depth 1 origin \
  43c6f329fb1fb528259a78f80b163e4ed1405c02
git -C tmp/codex/references/n8n-source/upstream sparse-checkout set \
  --no-cone --stdin < tmp/codex/references/n8n-source/sparse-paths.txt
git -C tmp/codex/references/n8n-source/upstream checkout --detach \
  43c6f329fb1fb528259a78f80b163e4ed1405c02
```

Never replace the exact fetch/checkout with current `master` without a new review.

## Exact sparse selection

Copy this tracked manifest verbatim to the ignored `tmp/codex/references/n8n-source/sparse-paths.txt` before reconstruction:

```text
/LICENSE.md
/package.json
/packages/frontend/editor-ui/package.json
/packages/frontend/@n8n/design-system/package.json
/packages/frontend/editor-ui/src/features/workflows/canvas/
/packages/frontend/editor-ui/src/features/shared/nodeCreator/
/packages/frontend/editor-ui/src/app/components/MainHeader/
/packages/frontend/editor-ui/src/app/components/WorkflowCanvasHost.vue
/packages/frontend/editor-ui/src/app/components/WorkflowCanvasHostBody.vue
/packages/frontend/editor-ui/src/app/views/CanvasAddButton.vue
/packages/frontend/editor-ui/src/app/views/NodeView.vue
/packages/frontend/editor-ui/src/app/views/NodeView.test.ts
/packages/frontend/editor-ui/src/app/views/WorkflowsView.vue
/packages/frontend/editor-ui/src/app/views/WorkflowsView.test.ts
/packages/frontend/editor-ui/src/features/execution/executions/components/global/
/packages/frontend/editor-ui/src/features/execution/executions/views/
/packages/frontend/editor-ui/src/features/execution/logs/
/packages/frontend/editor-ui/src/features/ai/instanceAi/components/AnsweredQuestions.vue
/packages/frontend/editor-ui/src/features/ai/instanceAi/components/ConfirmationFooter.vue
/packages/frontend/editor-ui/src/features/ai/instanceAi/components/InstanceAiQuestions.vue
/packages/frontend/editor-ui/src/features/ai/instanceAi/components/TaskChecklist.vue
/packages/frontend/editor-ui/src/features/ai/instanceAi/__tests__/InstanceAiQuestions.test.ts
/packages/frontend/editor-ui/src/features/ai/shared/agentsChat/
/packages/frontend/editor-ui/src/features/ai/shared/styles/_question-option-rows.scss
/packages/frontend/editor-ui/src/features/agents/components/AgentAdvancedPanel.vue
/packages/frontend/editor-ui/src/features/agents/components/AgentBuilderEditorColumn.vue
/packages/frontend/editor-ui/src/features/agents/components/AgentBuilderHeader.vue
/packages/frontend/editor-ui/src/features/agents/components/AgentBuilderTabPanel.vue
/packages/frontend/editor-ui/src/features/agents/components/AgentCapabilitiesSection.types.ts
/packages/frontend/editor-ui/src/features/agents/components/AgentCapabilitiesSection.utils.ts
/packages/frontend/editor-ui/src/features/agents/components/AgentCapabilitiesSection.vue
/packages/frontend/editor-ui/src/features/agents/components/AgentCard.vue
/packages/frontend/editor-ui/src/features/agents/components/AgentChatEmptyState.vue
/packages/frontend/editor-ui/src/features/agents/components/AgentChatMessageList.vue
/packages/frontend/editor-ui/src/features/agents/components/AgentChatPanel.vue
/packages/frontend/editor-ui/src/features/agents/components/AgentConfigTree.vue
/packages/frontend/editor-ui/src/features/agents/components/AgentConfirmationModal.vue
/packages/frontend/editor-ui/src/features/agents/components/AgentInfoPanel.vue
/packages/frontend/editor-ui/src/features/agents/components/AgentMiniEditor.vue
/packages/frontend/editor-ui/src/features/agents/components/AgentPanelHeader.vue
/packages/frontend/editor-ui/src/features/agents/components/AgentPreviewChatPage.vue
/packages/frontend/editor-ui/src/features/agents/components/AgentSectionEditor.vue
/packages/frontend/editor-ui/src/features/agents/components/AgentSubAgentsModal.vue
/packages/frontend/editor-ui/src/features/agents/components/AgentSubAgentsPanel.vue
/packages/frontend/editor-ui/src/features/agents/components/AgentTaskModal.vue
/packages/frontend/editor-ui/src/features/agents/components/AgentTypingIndicator.vue
/packages/frontend/editor-ui/src/features/agents/components/RichInteractionCard.vue
/packages/frontend/editor-ui/src/features/agents/components/WorkflowExecutionLogViewer.vue
/packages/frontend/editor-ui/src/features/agents/components/interactive/
/packages/frontend/editor-ui/src/features/agents/styles/
/packages/frontend/editor-ui/src/features/agents/agent.types.ts
/packages/frontend/editor-ui/src/features/agents/types.ts
/packages/frontend/editor-ui/src/features/agents/__tests__/AgentBuilderEditorColumn.spec.ts
/packages/frontend/editor-ui/src/features/agents/__tests__/AgentBuilderHeader.test.ts
/packages/frontend/editor-ui/src/features/agents/__tests__/AgentCapabilitiesSection.test.ts
/packages/frontend/editor-ui/src/features/agents/__tests__/AgentCard.test.ts
/packages/frontend/editor-ui/src/features/agents/__tests__/AgentChatMessageList.test.ts
/packages/frontend/editor-ui/src/features/agents/__tests__/AgentChatPanel.test.ts
/packages/frontend/editor-ui/src/features/agents/__tests__/AgentConfigTree.test.ts
/packages/frontend/editor-ui/src/features/agents/__tests__/AgentSubAgentsModal.spec.ts
/packages/frontend/editor-ui/src/features/agents/__tests__/AgentSubAgentsPanel.spec.ts
/packages/frontend/editor-ui/src/features/agents/__tests__/AgentTaskModal.test.ts
/packages/frontend/editor-ui/src/features/agents/__tests__/InteractiveCard.test.ts
/packages/frontend/editor-ui/src/features/agents/__tests__/N8nChatActionCard.test.ts
/packages/frontend/editor-ui/src/features/agents/__tests__/WorkflowExecutionLogViewer.spec.ts
/packages/frontend/@n8n/design-system/src/css/
/packages/frontend/@n8n/design-system/src/components/N8nActionToggle/
/packages/frontend/@n8n/design-system/src/components/AskAssistantChat/
/packages/frontend/@n8n/design-system/src/components/N8nButton/
/packages/frontend/@n8n/design-system/src/components/N8nCard/
/packages/frontend/@n8n/design-system/src/components/N8nChatInput/
/packages/frontend/@n8n/design-system/src/components/N8nDialog/
/packages/frontend/@n8n/design-system/src/components/N8nEmptyState/
/packages/frontend/@n8n/design-system/src/components/N8nFormInput/
/packages/frontend/@n8n/design-system/src/components/N8nIconButton/
/packages/frontend/@n8n/design-system/src/components/N8nInlineTextEdit/
/packages/frontend/@n8n/design-system/src/components/N8nInput/
/packages/frontend/@n8n/design-system/src/components/N8nMarkdown/
/packages/frontend/@n8n/design-system/src/components/N8nNotice/
/packages/frontend/@n8n/design-system/src/components/N8nPromptInputSuggestions/
/packages/frontend/@n8n/design-system/src/components/N8nRadioButtons/
/packages/frontend/@n8n/design-system/src/components/N8nSelect/
/packages/frontend/@n8n/design-system/src/components/N8nSuggestedActions/
/packages/frontend/@n8n/design-system/src/components/N8nTabs/
/packages/frontend/@n8n/design-system/src/components/N8nTag/
/packages/frontend/@n8n/design-system/src/components/N8nText/
/packages/frontend/@n8n/design-system/src/components/N8nTooltip/
/packages/frontend/@n8n/design-system/src/components/N8nTree/
!**/*.ee.*
!**/.ee/**
```

## Why this exists

n8n already solves many ordinary-user interaction problems that Banksia should not rediscover from screenshots alone: a large canvas, discoverable add affordances, selected-item editing, compact controls, autosave/publish framing, lists and empty states, execution browsing, logs, assistant questions, chat receipts, confirmations, responsive behavior, keyboard handling, and component tests.

Banksia is not an n8n dataflow product. The source is evidence about mature UI composition and interaction engineering. Banksia's target docs, generated product API, responsibility-tree semantics, controller truth, terminology, and accessibility requirements remain authoritative.

## License and provenance boundary

Read the ignored checkout's `upstream/LICENSE.md` before using this reference. At the pinned commit, ordinary source is under n8n's Sustainable Use License; files with `.ee.` in their filename or `.ee` in a directory have separate enterprise restrictions. The sparse selection contains no such enterprise files.

The reviewed license file SHA-256 is `d2f621f59aa4c10eab79b6333e59d9d3d5b53307dcfd16dbd75e40e679e84965`. A refresh must record the new commit and license digest and repeat the enterprise-path search before any delegation uses it.

Banksia is currently MIT-licensed. Therefore:

- keep this clone under ignored `tmp/`; do not package, publish, or commit it;
- do not import n8n packages or copy Vue, TypeScript, stores, tests, HTML structure, SCSS/CSS, tokens, icons, images, strings, or assets into Banksia;
- do not translate source line-for-line from Vue to React;
- independently implement Banksia's React/Tailwind components from the Banksia contract after recording the interaction decision learned; and
- stop for a separate license/provenance decision if a desired implementation would be substantially derived from n8n code rather than the general design behavior.

The source can teach behavior, component boundaries, states, focus handling, responsive strategies, and test cases. It cannot become a hidden second codebase or license path.

## Reference packets

Every WP-09, WP-10, or WP-11 delegated slice must read this file and the exact packet below that matches its owned surface. The brief must name the individual upstream paths it used and record `adopt`, `adapt`, or `reject` for each learned pattern.

### A. Product shell, library, and publish framing

Read:

- `upstream/packages/frontend/editor-ui/src/app/components/MainHeader/`
- `upstream/packages/frontend/editor-ui/src/app/views/WorkflowsView.vue`
- `upstream/packages/frontend/editor-ui/src/app/views/WorkflowsView.test.ts`
- `upstream/packages/frontend/editor-ui/src/features/agents/components/AgentCard.vue`
- `upstream/packages/frontend/editor-ui/src/features/agents/__tests__/AgentCard.test.ts`
- selected primitives under `upstream/packages/frontend/@n8n/design-system/src/components/`

Study page hierarchy, clear primary actions, draft/publish separation, compact cards, empty/loading/error states, and responsive action placement. Reject n8n activation terminology, project/credential/enterprise surfaces, dataflow semantics, and visual branding.

### B. Workflow Studio canvas and add-child interaction

Read:

- `upstream/packages/frontend/editor-ui/src/features/workflows/canvas/`
- `upstream/packages/frontend/editor-ui/src/features/shared/nodeCreator/`
- `upstream/packages/frontend/editor-ui/src/app/components/WorkflowCanvasHost.vue`
- `upstream/packages/frontend/editor-ui/src/app/components/WorkflowCanvasHostBody.vue`
- `upstream/packages/frontend/editor-ui/src/app/views/CanvasAddButton.vue`
- `upstream/packages/frontend/editor-ui/src/app/views/NodeView.vue`
- the curated Workflow Studio screenshot packet listed below

Study canvas layering, selection, pan/zoom/fit/tidy controls, pending states, tooltips, compact card geometry, drawer obstruction, focus, and tests. Banksia adapts these into one horizontal responsibility tree with exactly one trailing Add child control. Reject arbitrary graph edges, typed ports, multiple plus handles, dataflow/run controls, free placement, and node-type selection.

### C. Member editing and team configuration

Read:

- `upstream/packages/frontend/editor-ui/src/features/workflows/canvas/experimental/components/ExperimentalNodeDetailsDrawer.vue`
- `upstream/packages/frontend/editor-ui/src/features/agents/components/AgentBuilderEditorColumn.vue`
- `upstream/packages/frontend/editor-ui/src/features/agents/components/AgentConfigTree.vue`
- `upstream/packages/frontend/editor-ui/src/features/agents/components/AgentCapabilitiesSection.vue`
- `upstream/packages/frontend/editor-ui/src/features/agents/components/AgentInfoPanel.vue`
- `upstream/packages/frontend/editor-ui/src/features/agents/components/AgentSectionEditor.vue`
- `upstream/packages/frontend/editor-ui/src/features/agents/components/AgentSubAgentsPanel.vue`
- their selected tests in `upstream/packages/frontend/editor-ui/src/features/agents/__tests__/`

Study context preservation, progressive disclosure, section grouping, inline validation, autosave feedback, subagent/team discoverability, and small-screen behavior. Banksia exposes only title, purpose, instruction, advanced provider settings, and default-off built-in capabilities. Reject tools, skills, memory, credentials, schedules, channels, external MCP, and generic agent-builder concepts.

### D. Run list, Run Studio, actions, and logs

Read:

- `upstream/packages/frontend/editor-ui/src/features/execution/executions/components/global/`
- `upstream/packages/frontend/editor-ui/src/features/execution/executions/views/`
- `upstream/packages/frontend/editor-ui/src/features/execution/logs/`
- `upstream/packages/frontend/editor-ui/src/features/agents/components/WorkflowExecutionLogViewer.vue`
- `upstream/packages/frontend/editor-ui/src/features/agents/__tests__/WorkflowExecutionLogViewer.spec.ts`

Study scan-friendly lists, filtering, selected-run context, loading/empty/error states, bounded logs, truncation communication, cancellation affordances, and responsive detail layout. Banksia receives only semantic Task/Run product data. Reject raw execution internals, node data, technical event taxonomy, token usage, trace/tool details, and n8n status semantics.

### E. Operator, questions, confirmations, and receipts

Read:

- `upstream/packages/frontend/editor-ui/src/features/ai/instanceAi/components/InstanceAiQuestions.vue`
- `upstream/packages/frontend/editor-ui/src/features/ai/instanceAi/components/AnsweredQuestions.vue`
- `upstream/packages/frontend/editor-ui/src/features/ai/instanceAi/components/ConfirmationFooter.vue`
- `upstream/packages/frontend/editor-ui/src/features/ai/instanceAi/__tests__/InstanceAiQuestions.test.ts`
- `upstream/packages/frontend/editor-ui/src/features/ai/shared/agentsChat/`
- `upstream/packages/frontend/editor-ui/src/features/agents/components/AgentChatPanel.vue`
- `upstream/packages/frontend/editor-ui/src/features/agents/components/AgentChatMessageList.vue`
- `upstream/packages/frontend/editor-ui/src/features/agents/components/AgentConfirmationModal.vue`
- `upstream/packages/frontend/editor-ui/src/features/agents/components/RichInteractionCard.vue`
- `upstream/packages/frontend/editor-ui/src/features/agents/components/interactive/`
- their selected tests and the curated Operator screenshot packet listed below

Study one-question-at-a-time flow, full-width choices, keyboard shortcuts, Other input, progress, draft preservation, final submission, answered receipts, confirmation boundaries, message density, composer locking, retryable errors, and responsive chat layout. Banksia keeps its typed 1–3-question contract and fresh provider-turn boundary. Reject suspended-model semantics, raw tools, thinking traces, generic interactive payloads, and automatic side effects.

### F. Visual primitives and accessibility behavior

Read only the primitives relevant to the component being built under:

- `upstream/packages/frontend/@n8n/design-system/src/components/`
- `upstream/packages/frontend/@n8n/design-system/src/css/`

Study density, spacing relationships, focus, disabled/selected states, labels, tooltips, empty states, responsive behavior, and component tests. Do not copy tokens or CSS values. Define a distinct Banksia token system and validate it against Banksia screenshots and accessibility gates.

## Visual reference packet

The following image files live only under the ignored `tmp/codex/references/n8n-ui/` study directory. They are not shipped assets and must not be linked as tracked product dependencies:

| Packet | Image | Banksia use |
| --- | --- | --- |
| Operator | `operator/question-first.png` | One-question-at-a-time hierarchy, full-width options, progress, Other, and an explicit waiting state. |
| Operator | `operator/question-final-selected.png` | Selected-row feedback, Back, progress, and one final Continue action. |
| Operator | `operator/answers-and-building.png` | Compact answer receipt and human-readable progress without raw tool or reasoning traces. |
| Workflow Studio | `workflow-studio/horizontal-expanded-team.png` | Compact recursive cards and selected-Member emphasis after removing node/socket semantics. |
| Workflow Studio | `workflow-studio/add-child-sibling-branch.png` | Primary deep-team geometry: lead left, deeper generations right, siblings stacked vertically, and connectors meaning ownership only. |
| Workflow Studio | `workflow-studio/add-child-selected-member.png` | Selected-Member attachment and one trailing Add child affordance. |
| Workflow Studio | `workflow-studio/multiple-plus-avoid.png` | Negative reference: reject multiple typed ports or multiple visible add controls. |
| Workflow Studio | `workflow-studio/tidy-control.png` | Compact Tidy placement and tooltip; Tidy changes derived layout while Fit changes viewport only. |

Every use names the exact image, the interaction principle it supports, and the Banksia owner that supplies data and semantics. Surrounding n8n branding, navigation, strings, and product behavior are out of scope.

## Mandatory delegated-slice protocol

Before editing a UI or UI-facing product API, every delegated slice must add this information to its brief and return it with evidence:

```text
n8n reference packet and pinned commit:
Exact upstream files read:
Banksia owner contract and product data used:
Adopted interaction principles:
Adapted principles and why:
Rejected n8n concepts and why:
Nontechnical user scenario exercised:
Accessibility/responsive states exercised:
Provenance check (no copied/imported source or assets):
```

Reading the entire clone without naming the relevant files is not sufficient. Copying a component because it looks close is not sufficient. The slice must show how a specific mature interaction was translated into Banksia's simpler responsibility-tree or Run model for a person who does not know agent-runtime terminology.

## Nontechnical usability standard

For every screen and UI-facing backend response, test this sequence:

1. **Recognize:** can a person tell what this page/card is for without knowing Banksia runtime nouns?
2. **Act:** is the next primary action obvious and phrased as user intent?
3. **Predict:** does the UI explain material effect, scope, and destructive consequence before action?
4. **Recover:** do pending, empty, conflict, offline, rejected, and retry states give one safe next action without exposing machinery?
5. **Confirm:** after acceptance, does controller truth produce a concise receipt and preserve Undo where the target allows it?

Advanced provider and capability settings use progressive disclosure and plain consequences. The backend supplies semantic state, legal actions, confirmation requirements, typed inputs, and human-safe errors; the browser does not decode runtime records to invent them.

## Integrity checks

From `tmp/codex/references/n8n-source/upstream`:

```bash
git rev-parse HEAD
git symbolic-ref -q HEAD
git status --short
git sparse-checkout list
find . -path './.git' -prune -o -type f \
  \( -name '*.ee.*' -o -path '*/.ee/*' \) -print
```

Expected commit is the pinned value above, symbolic-ref returns no branch (detached pin), status is clean, and the enterprise file search returns no path.
