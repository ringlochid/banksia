# AutoClaw Console

Status: scaffold

This app owns the browser console implementation for AutoClaw runtime control and definition authoring.

## Source truth

- Backend controller contracts, current docs, and generated OpenAPI types own route, field, state, and action truth.
- The design handoff owns visual language, page states, spacing, typography, interaction cadence, and screenshot parity targets.
- When those disagree, patch the owning contract or design handoff before encoding behavior in React.
- The console owns its implementation token vocabulary in `src/styles/tokens.css`; use `--ac-*` custom properties even when the prototype CSS uses another prefix.
- Extract reusable colors, typography, spacing, sizes, radii, borders, shadows, and status treatments from the design handoff before building page-specific components.
- Do not copy design-repo static HTML, page-local CSS selectors, or inline prototype JavaScript into this app.

## Source layout

```text
src/
  app/              app bootstrap, router, providers, runtime config
  api/              API client, SSE helpers, generated OpenAPI types
  styles/           tokens and Tailwind entry CSS
  components/ui/    reusable primitives
  components/layout/ shared shell and layout primitives
  features/         product-owned pages and flows
  mocks/            MSW handlers and browser-only API fixtures
  lib/              small responsibility-named helpers
```

Feature folders should stay aligned with the product page model:

```text
features/
  tasks/
  task-detail/
  human-requests/
  command-runs/
  definitions/
  definition-editor/
  task-start/
```

Internal route fixtures live under `src/app/` instead of `src/features/` so product feature
folders stay page-owned.

## Naming and readability

- Use `PascalCase.tsx` for component files that primarily export one component.
- Use lower kebab-case for non-component modules: `task-event-mappers.ts`, `command-run-actions.ts`.
- Use `camelCase` for view-model fields, hooks, mappers, and local helpers.
- Keep generated OpenAPI names untouched; translate snake_case controller fields in explicit mappers.
- Name render-ready types by UI role: `TaskRow`, `TaskEventItem`, `HumanRequestItem`, `CommandRunRow`, `DefinitionSummary`.
- Use `on*` for callback props and `handle*` for local event handlers.
- Keep page components as orchestration surfaces; extract rows, forms, drawers, tabs, logs, and disclosure content when they own behavior or repeat.
- Keep Tailwind class strings token-backed and scan-friendly; extract repeated clusters into primitives, variant helpers, or token-backed CSS.

## Token contract

`src/styles/tokens.css` is the implementation token layer. `src/styles/tailwind.css` maps those tokens into Tailwind v4 theme variables.

Token families should stay semantic and reusable:

- colors: background, surface, outline, foreground, muted text, action, active, danger
- typography: body, display, mono stacks plus label, utility, compact, body, and display sizes
- spacing and sizes: page gutters, control height, icon-control size
- shape: small, medium, control, card, and shell radii
- elevation: hairline, panel, shell, popover shadows

Add new tokens only when a repeated design decision needs a shared name.

## Test layout

```text
tests/
  unit/         mappers, reducers, API helpers, view-models
  component/    primitives, layout shells, feature components
  integration/  MSW-backed API flows and SSE state transitions
  e2e/          Playwright browser flows
  visual/       screenshot and design-parity fixtures
  fixtures/     OpenAPI-shaped fake data
```

## Commands

Use root Make targets by default:

```bash
make console-install
make console-openapi-generate
make check-console
```

Use `make console-e2e` when Playwright browser dependencies are available and the touched slice changes page-level browser behavior.

## Package candidates

Do not install the whole list upfront. Add a package only when a feature owns the need and the corresponding console gate remains green.

- `clsx`, `tailwind-merge`, `class-variance-authority`: class composition and primitive variants once `Button`, `StatusChip`, `Pane`, and form controls grow real variants.
- `@tanstack/react-query`: server-state caching, invalidation, request retries, and mutation coordination once API-backed pages leave the scaffold stage.
- `zod`: runtime validation for console config, route/query params, and browser-local form drafts that need checks beyond TypeScript.
- `react-hook-form` and `@hookform/resolvers`: definition authoring and task-start forms once field count and validation make controlled inputs noisy.
- `@radix-ui/react-dialog`, `@radix-ui/react-popover`, `@radix-ui/react-tooltip`, `@radix-ui/react-tabs`, `@radix-ui/react-dropdown-menu`: accessible primitives when custom modals, popovers, tabs, and menus would be easy to get wrong.
- `@tanstack/react-table`: dense task, request, command-run, and definition tables once sorting, filtering, column visibility, and keyboard behavior matter.
- `@tanstack/react-virtual`: long event streams and command-run logs if real data volume makes DOM size a problem.
- `date-fns` or `luxon`: predictable time formatting once relative/local time display expands beyond a tiny helper.
- `eslint-plugin-jsx-a11y`: lintable accessibility coverage for JSX.
- `prettier-plugin-tailwindcss`: deterministic Tailwind class ordering once class strings become substantial.
