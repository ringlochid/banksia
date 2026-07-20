# Standards writing standard

Status: Reference

Use this guide when creating, renaming, reorganizing, or refactoring the [root agent contract](../../AGENTS.md), the [repo coding standard](../../STYLE.md), or files under the [standards index](./README.md).

## Goals

- keep the standards stack easy to enter and easy to maintain
- keep authority obvious at the root
- keep long-form guidance grouped by real concern
- reduce duplication, drift, and naming noise
- make the standards files themselves follow the same structural discipline they require from code

## Root contract rule

Keep these files at the repo root:

- the [root agent contract](../../AGENTS.md)
- the [repo coding standard](../../STYLE.md)

Rules:

- `AGENTS.md` is the root operational contract
- `STYLE.md` is the root measurable coding-standard contract
- neither file should be moved into the [standards index](./README.md)
- both files should stay concise, authoritative, and link outward to deeper standards instead of becoming books

## Standards tree rule

Use the [standards index](./README.md) for long-form guidance only.

Preferred structure:

```text
.agents/standards/
  README.md
  standards-writing.md
  code/
  structure/
  docs/
```

Rules:

- use shallow grouping by dominant concern
- do not create extra nested folders unless the file count or ownership split really demands it
- prefer one extra level of grouping at most
- avoid keeping a growing flat directory once several files naturally belong to distinct concern groups

## Concern grouping rule

Group long-form standards by concern:

- `code/`: code-writing and symbol-level rules
- `structure/`: source tree, package, runtime, integration, and test layout rules
- `docs/`: docs information architecture and docs-writing structure rules

For AutoClaw, the preferred grouped files are:

- [readability and refactor standard](./code/readability-refactor.md)
- [naming standard](./code/naming.md)
- [repo layout standard](./structure/repo-layout.md)
- [source layout standard](./structure/source-layout.md)
- [test structure standard](./structure/test-structure.md)
- [integration boundary standard](./structure/integration-boundaries.md)
- [Docs structure guide](./docs/docs-structure.md)

## Filename rule

- prefer lowercase markdown filenames in kebab-case
- use filenames that separate words clearly and read well in URLs and sidebars
- keep filenames stable once they become canonical
- do not encode chronology, version suffixes, or temporary migration wording in standard-file names

Prefer:

- `readability-refactor.md`
- `naming.md`
- `repo-layout.md`
- `source-layout.md`
- `test-structure.md`
- `docs-structure.md`
- `integration-boundaries.md`
- `standards-writing.md`

Avoid:

- `readability.md` when the longer current name is the canonical file
- `sourcelayout.md`
- `repolayout.md`
- `teststructure.md`
- `repo-layout-v2.md`
- `new-standards-final.md`

## Markdown linking rule

Make the standards more wiki-ish by default.

Rules:

- prefer relative markdown links over raw path mentions when referring to other repo files
- use markdown links for nearby standards, root contracts, and closely related docs
- keep links human-readable and path-stable
- do not use filename labels such as `README.md` or `source-layout.md` as navigation text when a human-readable title would do
- use inline code for literal paths only when the path itself is the subject, not when the text is functioning as navigation
- when a subtree needs a front door, keep the file named `README.md` but label inbound links by the subtree title, not by the filename

Prefer:

- [repo coding standard](../../STYLE.md)
- [standards index](./README.md)
- [source layout standard](./structure/source-layout.md)

Avoid:

- plain prose like `.agents/standards/source-layout.md` when a direct relative markdown link would do
- filename-label links whose visible text is the literal markdown filename when the link is just navigation
- raw absolute paths in standards files

## Standard file template rule

Long-form standard files should generally use this order:

1. title
2. `Status: Reference`
3. `Use this guide when ...`
4. `## Goals`
5. the main rule sections
6. transitional or exception sections when needed
7. `## Review checklist`
8. `## Related` when cross-links help

Not every file needs every section, but the structure should stay recognizable.

## Standards self-discipline rule

The standards stack should follow the same docs hygiene it requires elsewhere.

Rules:

- standards files should use human-readable titles and human-readable navigational link labels
- when a standards subtree needs a front door, treat `README.md` as the owner file and avoid parallel filename-branded link labels that compete with the subtree title
- if a standards page mentions a filename because the filename itself matters, keep that mention in inline code or prose rather than turning it into filename-style navigation text

## Root file structure rule

### `AGENTS.md`

Keep mainly:

- repo purpose
- authority split
- mandatory read order
- execution contract
- testing/verification expectations
- delegation rules
- completion rule

### `STYLE.md`

Keep mainly:

- measurable rules
- thresholds
- naming/import/layout constraints
- stack-specific rules
- pointers to long-form standards

Move examples, long rationale, and operational playbooks into the [standards index](./README.md).

## One-file-one-concern rule

- each long-form standards file should have one dominant concern
- if a standards file mixes two equally large concerns, split it
- if two files keep repeating the same explanation, merge or factor that shared guidance into the better owner file

## Transitional rule discipline

- put steady-state guidance before transitional guidance
- isolate migration-specific notes under a small transitional section when needed
- do not smear the same migration explanation across many standard files unless each file truly needs its own local version of it

## Canonical wording rule

When the same repo-level rule appears across standards files:

- keep the same core wording
- keep the same term for the same concept
- avoid introducing slightly different paraphrases that drift semantically over time

Examples worth keeping canonical:

- canonical backend package
- transport layers stay thin
- phase-numbered test trees are transitional
- domain-first runtime structure

## Size discipline

Use these as review triggers, not absolute laws:

- `AGENTS.md`: target <= 160 lines when practical
- `STYLE.md`: target <= 160 lines when practical
- `.agents/standards/README.md`: target <= 60 lines when practical
- long-form standards: split or tighten once they become obviously hard to scan or maintain

If a file grows because the concern is truly broad, prefer stronger internal structure before creating a shallow duplicate file.

## Review checklist

- is the root contract still obvious from the repo root
- are long-form standards grouped by real concern
- do filenames use clear kebab-case
- are cross-references mostly relative markdown links
- do navigational links use human-readable labels instead of `.md` filenames
- does each standard file have one dominant concern
- are steady-state rules stated before transitional exceptions
- are the standards files themselves following the same structure discipline they demand from code

## Related

- [standards index](./README.md)
- [source layout standard](./structure/source-layout.md)
- [repo layout standard](./structure/repo-layout.md)
- [readability and refactor standard](./code/readability-refactor.md)
- [naming standard](./code/naming.md)
