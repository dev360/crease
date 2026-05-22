# Authoring templates

A template is a YAML file that declares the entities crease should extract
from an xlsx, where each one lives, and what its fields mean. The
templates under [`test_cases/`](https://github.com/dev360/crease/tree/main/test_cases)
in the repository double as worked examples for each layout pattern.

!!! note "Placeholder page"
    This guide is being filled out. For now, the [README](https://github.com/dev360/crease#readme)
    and [test_cases/](https://github.com/dev360/crease/tree/main/test_cases) are the
    canonical reference.

## Skeleton

```yaml
template_id: orders
description: Order export from acme.

entities:
  - name: order
    cardinality: many        # one | many
    locate:
      tab: Orders
      orientation: flat      # flat | property_sheet | anchored
      header_row: 0
    fields:
      - name: order_id
        source_column: order_id
        type: string
        pattern: ^ORD-\d{4}$
```

See the [Reference > Template](../reference/template.md) page for the full
schema with every field documented.

## Versioning

A template's `version:` field gates which grammar features are
recognised at load time. Today there are two values:

- `version: 1` (the default) — the original grammar: `entities:`,
  `locate:`, `filename_pattern:`, etc.
- `version: 2` — adds the top-level `blocks:` declaration and the
  `Entity.block:` reference field for repeating sections within a
  tab. See [Repeating sections (`blocks:`)](blocks.md).

Loaders reject `blocks:` declarations under `version: 1` rather than
silently ignoring them, so an older runtime never produces
half-extracted output against a v2 template.

## Disambiguating duplicated headers

If two header cells in the same row carry the same normalized text, a
field with `source_column: "DATE"` is ambiguous — there are two columns
that could match. Crease emits a `header_duplicated` warning and binds
to the first occurrence so extraction still proceeds. To bind a specific
field to a specific occurrence, set `source_column_index:` (0-indexed
across the matches in the header row):

```yaml
fields:
  - name: open_date
    source_column: "DATE"
    source_column_index: 0      # first DATE column
    type: date
  - name: close_date
    source_column: "DATE"
    source_column_index: 1      # second DATE column
    type: date
```

Without `source_column_index`, both fields would bind to the same column
and `report.errors()` would contain a `header_duplicated` entry.

## Skipping rows during extraction

When a worksheet interleaves data with marker, subtotal, or grand-total
rows that have the same column geometry as real records, use
`locate.skip_row_if` to drop them before extraction. Each list entry is
a `LocateSkipRule`; if any one matches, the row is silently omitted
from the canonical output (no row error). This is the top-level Locate
filter; it is distinct from the block-scoped `SkipRowRule` (which uses
single-column patterns inside a block instance, see
[blocks](blocks.md)).

```yaml
locate:
  tab: Orders
  orientation: flat
  header_row: 0
  skip_row_if:
    # subtotal rows: blank discriminator column
    - all_blank: [customer]
    # day-of-week marker rows
    - column: label
      value_pattern: "^(MONDAY|TUESDAY|WEDNESDAY|THURSDAY|FRIDAY|SATURDAY|SUNDAY)$"
    # grand-total row: blank discriminator AND populated total
    - all_blank: [site]
      non_blank: [head_count]
```

Predicates compose by AND on the same rule (a rule with both
`all_blank` and `non_blank` matches when both lists are satisfied) and
by OR across rules. `value_pattern` is a regex full-matched against the
stringified cell value; combine it with `column:` to pin a single
column.

## Disambiguating anchored labels

When a worksheet stacks two cover-sheet-style blocks side by side and
both carry the same labels (a "REPORTING" block in column A and a
"BILLING" block in column D, each with its own `Company:` /
`Email:` rows), an `anchor` whose `label_match: "Company:"` would
default to the first hit. Two optional fields scope the search:

- `column: int` — restrict the scan to a single 0-indexed column.
- `nth: int` — pick the Nth match (1-indexed; default 1).

```yaml
fields:
  - name: reporting_company
    type: string
    anchor: { label_match: "Company:", column: 0, value_at: right, offset: 1 }
  - name: billing_company
    type: string
    anchor: { label_match: "Company:", column: 3, value_at: right, offset: 1 }
  - name: section_two_carrier
    type: string
    anchor:
      label_match: "SHIPPING INFORMATION"
      nth: 2                # the second occurrence of the label
      value_at: right
      offset: 2
```

## Time fields

`type: time` accepts native `datetime.time` cells, datetime cells (the
time component is extracted), and string cells. Strings are normalized
so that `a.m.` / `p.m.` markers match `%p` (i.e. `"7:30 a.m."` becomes
`"7:30 AM"`) and then parsed against an optional list of
`time_formats`:

```yaml
fields:
  - name: collection_time
    source_column: "collection_time"
    type: time
    time_formats:
      - "%I:%M %p"
      - "%H:%M"
```

If no `time_formats` are given, ISO-format strings (`"09:30:00"`,
`"09:30"`) still parse. The canonical value is always the ISO string
form of the time (mirroring how `date` / `datetime` fields project).

## Regex null collapse

When a worksheet uses *patterned* placeholders for missing values
(``[Company]``, ``[Email]``, ``[Fax]``), enumerating each variant in
``null_tokens`` is brittle. ``null_patterns`` accepts a list of full-match
regexes layered the same way as ``null_tokens`` — field overrides
template overrides nothing:

```yaml
null_patterns:
  - "^\\[.+\\]$"           # any bracketed placeholder
  - "^TBD\\s*\\d*$"        # TBD, TBD1, TBD-2, ...
entities:
  - name: row
    locate: { tab: Sheet1, orientation: flat, header_row: 0 }
    fields:
      - { name: email, source_column: "email", type: email, nullable: true }
```

## Stopping mid-tab on a pattern

``data_ends_at`` already supports an exact-string ``value_match``. When
the sentinel row's text varies in trivial ways (double-space, trailing
colon, capitalization), use ``value_pattern`` with a regex:

```yaml
data_ends_at:
  type: value_pattern
  column: 0
  value_pattern: "^AVG AGE\\s+\\d+\\+\\s*:?\\s*$"
```

## Free-text banner rows

Some reports carry occasional free-text "annotation" rows interleaved
with data — `-- REVISED --`, dividers, notes in column A. Use
``row_is_annotation_if`` with ``only_columns_populated: N`` to drop any
row where N or fewer columns are populated, before field coercion runs:

```yaml
locate:
  tab: Sheet1
  orientation: flat
  header_row: 0
  row_is_annotation_if:
    - only_columns_populated: 1
```

## Forward-filling grouping columns

Schedules and roll-ups often set a grouping column (day, grower,
region) on the *first* row of a group and leave it blank on the
continuation rows. ``locate.forward_fill: [col, ...]`` propagates the
last non-blank value of each listed column down through blank rows
before field coercion runs:

```yaml
locate:
  tab: Sheet1
  orientation: flat
  header_row: 0
  forward_fill: [day, grower]
fields:
  - { name: day, source_column: "day", type: string }
  - { name: grower, source_column: "grower", type: string }
  - { name: houses, source_column: "houses", type: string }
```

A continuation row with `[None, None, "5-6", 50]` inherits `day` /
`grower` from the row above; the moment a non-blank value appears, it
becomes the new "last seen" value for that column.

## Templates that pin the read backend

Crease reads spreadsheets through two interchangeable backends — calamine
(the default; reads `.xlsx`, `.xls`, `.xlsb`, `.ods`) and openpyxl (`.xlsx`
only, but exposes cell metadata calamine does not).

One template feature forces openpyxl: **`locate.skip_hidden_rows: true`**.
Calamine doesn't surface the row-hidden flag, so a template that needs to
drop hidden rows is auto-dispatched to openpyxl. The side effect is that
such templates can't read `.xls` / `.xlsb` / `.ods` — those formats live
on the calamine path only.

```yaml
entities:
  - name: order
    locate:
      tab: Orders
      orientation: flat
      skip_hidden_rows: true   # → openpyxl backend; .xlsx only
```

If you'd rather have multi-format support and accept that hidden-row
detection won't fire, override at call time:

```python
crease.extract("orders.xls", template, engine="calamine")  # silently no-ops skip_hidden_rows
```
