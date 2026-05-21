# Repeating sections within a single tab

## What this case tests

Each tab contains repeating sub-sections delimited by two cells:

- **Start anchor:** column D, value `"DELIVERY SCHEDULE"`
- **End anchor:** column A, value matching `^={3,}$` (greedy — see below)

Between those bounds, each section has a date row (in column D, formats like
`MONDAY 4-13-2026` and `TUESDAY 4/14/26`), a projected-load summary block to
ignore, a column header row, and depot-grouped data rows with unlabeled
subtotal rows between groups. The section date is the most important field on
every output row but it lives in a narrative cell ABOVE the table — the
pre-`blocks` grammar could not express "repeat for each occurrence of this
anchor."

## How the new `blocks:` grammar handles it

Two top-level constructs:

1. `blocks:` declares the repeating region (`daily_section`) — anchors, the
   metadata captured per section instance (`delivery_date`, `day_of_week`),
   and the separator rows that should be ignored when an inner entity is
   scanned.
2. `entities:` (top-level, like today) declares `delivery`. The new
   `block: daily_section` field scopes that entity to each section instance.
   At extract time, the block's captures merge onto every delivery row.

Notable design refinements baked into this case:

- **Positional anchors.** `starts_at.column: D` and `ends_at.column: A` scope
  each anchor to a specific column. Without that, an `=====` row in some
  other column would close a block prematurely.
- **Column accepts int OR Excel letter.** Both `column: 3` and `column: D`
  validate; the schema coerces letter to 0-indexed int.
- **Greedy `ends_at`.** Each section contains intermediate `===` rows under
  the column header AND the end-of-section terminator. The default
  `strategy: last_in_block` picks the last match before the next block start.
- **`separator_rows` at block scope** replaces what would otherwise be a
  per-entity `skip_rows_matching` block — single source of truth for the
  rows the inner entity should silently skip (`===` separators and blank
  rows).
- **No nesting in v1.** A daily section that contained per-depot subsections
  could in principle be a block-inside-a-block, but the recursive grammar
  is deferred. Today's `depot` field is a column in the data table, which
  the flat entity machinery already handles.

## Status

**Failing test.** Until `blocks` ships, `template.yml` is rejected by
`Template.model_validate`. `expected.json` documents the target output;
`expected_issues.json` is `{verdict: "valid", issues: []}` since this case
exercises the happy path.
