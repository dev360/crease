# Repeating sections (`blocks:`)

Some reports pack multiple sections into one tab — a weekly schedule
with a separate sub-table per period, an invoice with a header row
followed by line items repeated for each contract, or a report that
interleaves a per-group title row with the detail rows underneath.

A flat `entities:` declaration can't say *"this entity repeats inside
a tab, anchored by start and end patterns, and a piece of metadata
above each section's table belongs on every row inside that section."*
That's what `blocks:` is for.

## The shape

```yaml
template_id: weekly_orders
version: 2                              # `blocks:` requires v2 templates

blocks:                                 # top-level region declarations
  - name: daily_section
    tab_pattern: ^W-\d+$
    starts_at:
      column: D                         # int (0-indexed) OR Excel letter
      cell_pattern: ^ORDER SCHEDULE$
    ends_at:
      column: A
      cell_pattern: ^={3,}$
      strategy: last_in_block           # last_in_block (default) | first_in_block
    separator_rows:                     # rows the inner entity should skip
      - { column: A, cell_pattern: ^={3,}$ }
      - { column: A, match_blank: true }
    captures:                           # per-instance metadata merged onto every row
      - field: order_date
        from:
          column: D
          cell_pattern: ^DAY (\d+-\d+-\d+)$
          regex_group: 1
          on_multiple: first            # first (default) | last | error
        type: date
        date_formats: ['%m-%d-%Y']
        required: true                  # zero matches => capture_no_match
        propagate: true                 # merge onto every entity row

entities:
  - name: order
    block: daily_section                # ← scope this entity to each block instance
    cardinality: many
    locate:
      orientation: flat                 # tab/tab_pattern forbidden here —
      header_anchor:                    # the block owns tab scope
        text: ORDER_ID
        match_mode: exact
    fields:
      - { name: order_id,   source_column: ORDER_ID, type: string, pattern: ^ORD-\d{4}$ }
      - { name: customer,   source_column: CUSTOMER, type: string }
      - { name: quantity,   source_column: QUANTITY, type: integer, minimum: 1 }
```

For a tab like

| row | A | … | D |
|---|---|---|---|
| 0 |   |   | ORDER SCHEDULE |
| 1 |   |   | DAY 4-13-2026 |
| 2 | ORDER_ID | CUSTOMER, QUANTITY |
| 3 | ORD-1001 | Acme Co. | 12 |
| 4 | ORD-1002 | Globex Corp | 7 |
| 5 | ==== |   |   |
| 6 |   |   | ORDER SCHEDULE |
| 7 |   |   | DAY 4-14-2026 |
| … |   |   |   |

every `ORD-` row comes out flat, with `order_date` from its section's
DAY-row merged in:

```python
[
  {"order_id": "ORD-1001", "customer": "Acme Co.",    "quantity": 12, "order_date": "2026-04-13"},
  {"order_id": "ORD-1002", "customer": "Globex Corp", "quantity":  7, "order_date": "2026-04-13"},
  ...
  {"order_id": "ORD-2007", "customer": "Hooli",       "quantity":  3, "order_date": "2026-04-14"},
]
```

## What a `Block` declares

| Field | Meaning |
|---|---|
| `name` | Internal handle; entities reference it via `block: <name>`. |
| `tab_pattern` | Optional regex on the sheet name. Omit → applies to every tab. |
| `starts_at` | The cell that opens an instance. A linear scan finds **every** match in the configured column. |
| `ends_at` | The cell that closes an instance. Optional — omit and the instance extends to `next_starts_at - 1` or EOF. |
| `separator_rows` | Row-skip rules applied inside this block's body so the inner entity doesn't have to repeat them. |
| `captures` | Per-instance metadata: scan a column, match a regex, coerce to a type, merge onto every row in the instance. |

The block grammar is intentionally **flat** in v1: a block has no
`body:` container and cannot nest other blocks. Entities reference a
single block by name. If a future layout needs two-level scoping, that
will land as composed blocks; it does not require reopening the schema.

## Greedy `ends_at` (the default)

Real-world section terminators reuse the same separator pattern that
appears *inside* the section (under the column header, between
sub-groups). The default `strategy: last_in_block` picks the **last**
match between `starts_at` and the next `starts_at` (or EOF). A
non-greedy default would close every section at the first separator
and silently drop most of the data.

Set `strategy: first_in_block` only when you're confident the closing
anchor is unique to the end of a section.

## Columns — int or Excel letter

`column:` accepts either form:

```yaml
starts_at: { column: 3, cell_pattern: ^ORDER SCHEDULE$ }    # 0-indexed
# is identical to
starts_at: { column: D, cell_pattern: ^ORDER SCHEDULE$ }    # letter
```

Single-letter only (`A`..`Z`). Multi-letter columns are out of scope
for v1.

## Cell-pattern matching, precisely

`cell_pattern` is applied as `re.fullmatch` against
`str(cell.value).strip()`. None and empty cells never match. That's
the same rule for `starts_at`, `ends_at`, `from`, and `separator_rows`.

To skip blank rows specifically, use the explicit form on a
`SkipRowRule`:

```yaml
separator_rows:
  - { column: A, match_blank: true }   # matches None or empty-string cells
```

Excel can't distinguish a truly-empty cell from one containing the
empty string at the storage level, so `match_blank` collapses both.

## Captures — picking up per-section metadata

A capture says *"inside this block instance, find a cell whose
contents match `cell_pattern`, take this regex group, coerce to this
type, and merge the result onto every emitted entity row."*

```yaml
captures:
  - field: order_date
    from:
      column: D
      cell_pattern: ^DAY (\d+-\d+-\d+)$
      regex_group: 1                   # 1 = first capture group; 0 = whole match
      on_multiple: first               # how to handle multiple hits inside one instance
    type: date
    date_formats: ['%m-%d-%Y', '%m/%d/%y']
    required: true
    propagate: true
```

| Knob | Default | What it does |
|---|---|---|
| `on_multiple` | `first` | `first` / `last` / `error`. Real-world sections sometimes repeat the metadata row by accident; `error` makes that loud. |
| `required` | `true` | Zero matches inside the instance → `capture_no_match` structural error. Set `false` to allow `null`. |
| `propagate` | `true` | `false` means the capture is still resolved (and can still raise errors) but is **not** merged onto rows. Useful when you want the capture for validation only. |
| `date_formats` | `[]` | For `type: date` / `type: datetime`. Each format is tried in order; first match wins. Unparseable values surface as `wrong_type` keyed to the capture field. |

## Tab targeting is owned by the block

When an entity sets `block:`, it **must not** also set
`locate.tab` / `locate.tab_pattern`. The block's `tab_pattern` is what
drives the sheet scan. The template loader rejects this collision
with `entity_tab_with_block` at load time, before any file is opened.

## Output shape: always flat

`extract()` returns the same shape it always has —
`{entity_name: [row, row, ...]}`. Every row carries the merged
captures from its enclosing block instance. There is no nested-dict
output mode, by design. If consumers want a tree, they group the flat
rows themselves on the captured keys.

`stream()` yields those same flat rows in source order. The streamer
buffers per-block-instance until that instance's captures are
resolved, then drains the rows — see
[Streaming large files](streaming.md) for the latency tradeoff.

## Validation rules that fire at template load

Catching these at `Template.model_validate` (rather than at extract
time) lets editors flag malformed templates before any file is opened.

| Rule | Triggers when… |
|---|---|
| blocks-requires-v2 | `blocks:` is declared but `version: 1`. |
| duplicate block name | Two entries in `blocks:` share `name`. |
| `block_ref_not_found` | `entity.block` names a block that isn't declared. |
| `entity_tab_with_block` | `entity.block` set AND `entity.locate.tab`/`tab_pattern` set. |
| `field_shadow_collision` | A capture on block B has the same `field` as a `FieldSpec.name` on an entity that targets B. |
| `multi-letter column` | Anything other than `A`..`Z` or a non-negative int in a `column:`. |
| `SkipRowRule exactly-one-mode` | A `separator_rows` rule with neither `cell_pattern` nor `match_blank: true`, or both. |

## Errors emitted at extract time

These show up on `result.errors` / `Report.errors()` with the existing
`Error` shape — same `type`, `loc`, `msg`, `ctx`, `severity` fields as
the rest of the taxonomy.

| `error.type` | Severity | Fires when… |
|---|---|---|
| `block_starts_not_found` | structural | A tab matches `tab_pattern` but `starts_at` never fires. |
| `block_unterminated` | structural | `ends_at` is configured but no candidate fires before the next `starts_at` or EOF. |
| `capture_no_match` | structural | A `required: true` capture matches zero cells in the instance. |
| `capture_multiple_matches` | structural | A capture with `on_multiple: error` matches more than once in the instance. |

See [Errors reference](../reference/errors.md) for the full taxonomy.

## Three matchers, one mental model

For historical reasons the locator vocabulary varies slightly by
context. Until they're unified in a later release:

| Where it lives | Field | Matching mode |
|---|---|---|
| `Locate.header_anchor` | `text` + `match_mode: exact \| contains \| regex` | Mode-driven |
| `Block.starts_at / ends_at`, `Capture.from`, `SkipRowRule` | `cell_pattern` | Always `re.fullmatch` against the stripped string |
| `SkipRowRule` | `match_blank: true` | Matches None or empty-string cells |

## Things v1 does not do

- **Nested blocks.** Single-level only. No `body.blocks`, no
  `block: [outer, inner]`.
- **Captures above `starts_at`.** A capture's `from` scan is bounded
  by the block instance's row range; it cannot reach above the start
  anchor.
- **Merged-cell expansion.** Anchors must reference the **top-left
  cell** of a merged region. Other cells of the merge return `None`.
- **Multi-column anchor.** `column:` is a single int (or letter). If
  the anchor lives in column C in week 1 and column D in week 2, that
  belongs in a separate template variant.

Each cut keeps the v1 grammar small enough to read in one sitting and
forward-compatible with the layouts those features would address.
[`test_cases/`](https://github.com/dev360/crease/tree/main/test_cases)
documents the supported shapes by example.
