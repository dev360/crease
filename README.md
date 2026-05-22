# crease

Declarative Excel-to-JSON extraction **and** validation. Apply a compact YAML
template to a spreadsheet file — `.xlsx`, `.xls`, `.xlsb`, or `.ods` — get
canonical JSON out plus structured per-cell errors. No spreadsheet-specific
code in your pipeline.

📖 **Docs:** [dev360.github.io/crease](https://dev360.github.io/crease/)

```bash
pip install crease
```

> **Status: 1.0** — published to PyPI as [`crease`](https://pypi.org/project/crease/). API surface is stable; breaking changes will be marked `feat!:` and bump the major version. See [ROADMAP.md](ROADMAP.md) for what's next.

---

## Why this exists

Excel parsing has well-documented failure modes that quietly cost money and
time. Crease is designed to make these *visible and structured* rather than
silent:

| Failure mode | Cost when it happens | How Crease handles it |
|---|---|---|
| Excel autoconverts `SEPT2` (gene) to `2-Sep` (date) — affects ~20% of genomics papers | Wrong data downstream, no warning | `treat_as_text` on the field; validator emits `wrong_type` with `likely_cause: excel_autoconvert` |
| Public Health England loses 15,706 COVID cases to silent row-overflow | 8-day contact-tracing gap during a pandemic | Per-template `min_data_rows` + `column_count_mismatch` detection; nothing fails silently |
| JPMorgan loses $6B because a VaR model required manual copy-paste between sheets | The whole loss | Canonical JSON flows from xlsx to downstream pipelines — the copy step disappears |
| Operator gets `#N/A` from VLOOKUP because `"Acme Corp"` had a trailing space | Hours of debugging | Always-on header normalization; per-field `normalize: trim` |
| `N/A`, `TBD`, `-` in cells trigger `wrong_type` everywhere | False positives bury real issues | Layered `null_tokens` — library defaults handle the common ones, templates and fields tighten or loosen |
| Headers move down a row when the customer adds a title line | Every subsequent file fails | `locate.header_anchor: "Order ID"` instead of `header_row: 3` |
| Operator hides "soft-deleted" rows; downstream consumers still process them | Cf. Lehman/Barclays' 179 unwanted trading contracts (2008) | `locate.skip_hidden_rows: true` |
| Customer sends `.xls` / `.xlsb` / `.ods` instead of `.xlsx` | Pipeline rejects the file; manual re-export | All four formats read out of the box — calamine handles the legacy ones |

The full catalog of patterns and supporting sources lives in
[ANECDOTES.md](ANECDOTES.md). The design philosophy: **fail loudly with row
and field coordinates rather than swallowing the failure into the canonical
output.**

---

## Quick start

A template describes *where* the data lives and *what* the fields mean. The
same template drives both extraction (cells → canonical JSON) and validation
(constraints → structured errors).

The API splits into three composable steps:

```python
import crease

template = crease.Template.load("templates/orders.crease.yml")

# 1. Extract — turn cells into canonical JSON
result = crease.extract("incoming.xlsx", template)
result.canonical["orders"][0]
# {"order_id": "ORD-1001", "customer_email": "a@acme.com",
#  "order_date": "2025-01-15", "quantity": 10, "unit_price": 25.50}

# 2. Validate — independent inspection step
report = crease.validate(result, template)
report.is_valid              # bool — true iff zero errors
report.errors()              # list[Error] — pydantic-shaped

# Or do extract + validate together
result, report = crease.check("incoming.xlsx", template)
```

Template paths are plain relative paths resolved from your working directory
— no implicit "same folder as the xlsx" convention.

The template that produced the output above (note: `pattern:`, `minimum:` etc.
are both *coercion hints* for extraction **and** *constraints* for validation):

```yaml
# templates/orders.crease.yml
template_id: orders
description: Order export from acme.

entities:
  - name: order
    cardinality: many
    locate:
      tab: Orders
      orientation: flat
      header_row: 0
    fields:
      - { name: order_id,       source_column: order_id,       type: string,  pattern: ^ORD-\d{4}$ }
      - { name: customer_email, source_column: customer_email, type: email }
      - { name: order_date,     source_column: order_date,     type: date }
      - { name: quantity,       source_column: quantity,       type: integer, minimum: 1 }
      - { name: unit_price,     source_column: unit_price,     type: number,  minimum: 0 }
```

---

## Getting your data out

`result.canonical` is a plain dict — no extra dependencies, no opinions. When
you want something richer, opt in:

```python
# Iterate as dicts
for order in result.iter("order"):
    pipeline.send(order)

# Project into a Pydantic model. Field matching is opportunistic by attribute
# name: fields the model doesn't declare are dropped silently; type mismatches
# raise crease.ValidationError.
from pydantic import BaseModel

class Order(BaseModel):
    order_id: str
    quantity: int      # the model can be a subset of the template's fields

orders: list[Order] = result.to_pydantic("order", model=Order)

# Project into a pandas DataFrame
df = result.to_pandas("order")
```

By default, every projection method **halts** if extraction produced any
errors — the library's whole pitch is "fail loudly with coordinates." To
opportunistically recover and keep the rows that did map cleanly:

```python
orders = result.to_pydantic("order", model=Order, allow_partial=True)
# rows that didn't validate are absent from `orders`.
# they're listed in result.report.errors() with row/field coordinates.
```

For `cardinality: one` entities, use `result.get("company")` /
`result.get("company", model=Company)` instead — iteration over a single
record is a category error.

---

## Streaming large files

For multi-hundred-thousand-row files, stream instead of materializing.
Streaming takes the same `model=` and `allow_partial=` arguments as the
materialized projections, so the shape stays symmetric:

```python
# Yields dicts
for order in crease.stream("big.xlsx", template, entity="order"):
    pipeline.send(order)

# Yields validated Pydantic instances
for order in crease.stream("big.xlsx", template, entity="order", model=Order):
    pipeline.send(order)
```

Memory stays bounded (~10MB) regardless of file size. Errors accumulate on
the session report rather than being yielded inline — the iterator returns
the happy path; the report owns the sad path.

---

## Multi-entity files

When one file has multiple shapes (cover sheet + per-region data tabs +
totals), declare each as its own entity:

```yaml
entities:
  - name: company                       # one record from the cover tab
    cardinality: one
    locate: { tab: Cover, orientation: property_sheet, label_col: 0, value_col: 1 }
    fields:
      - { name: company_name,  source_label: Company,       type: string }
      - { name: period,        source_label: Period,        type: string, pattern: ^Q[1-4]\s\d{4}$ }
      - { name: contact_email, source_label: Contact,       type: email }

  - name: order                         # many records from every "Region - X" tab
    cardinality: many
    locate:
      tab_pattern: ^Region - (.+)$
      orientation: flat
      header_row: 3
    fields:
      - { name: order_id, source_column: Order ID, type: string,  pattern: ^ORD-\d{4}$ }
      - { name: customer, source_column: Customer, type: string }
      - { name: total,    source_column: Total,    type: number,  minimum: 0 }
    enrich:
      - { field: region, source: tab_name_regex_group, group: 1 }

ignore_tabs: [Notes]
```

Use a session when you want both eager and streaming reads against the same file:

```python
with crease.open("incoming.xlsx", template) as session:
    company = session.get("company")                     # cardinality: one (eager)
    for order in session.stream("order", model=Order):   # cardinality: many (streaming)
        pipeline.send({**order.model_dump(), "_company": company["company_name"]})

    if not session.report().is_valid:
        log.warning(session.report().errors())
```

---

## Repeating sections within one tab

Some reports pack multiple sub-sections into a single tab — a weekly
schedule with one sub-table per day, separated by a `=====` row or a
recurring title. The `blocks:` grammar (template `version: 2`) lets you
declare the repeating region once, anchor each instance with start /
end patterns, and capture per-section metadata that gets merged onto
every row in that section:

```yaml
template_id: weekly_orders
version: 2

blocks:
  - name: daily_section
    tab_pattern: ^W-\d+$
    starts_at: { column: D, cell_pattern: ^ORDER SCHEDULE$ }
    ends_at:   { column: A, cell_pattern: ^={3,}$ }
    captures:
      - field: order_date
        from: { column: D, cell_pattern: ^DAY (\d+-\d+-\d+)$, regex_group: 1 }
        type: date
        date_formats: ['%m-%d-%Y']

entities:
  - name: order
    block: daily_section                # ← scope this entity to each block instance
    cardinality: many
    locate:
      orientation: flat
      header_anchor: { text: ORDER_ID, match_mode: exact }
    fields:
      - { name: order_id, source_column: ORDER_ID, type: string, pattern: ^ORD-\d{4}$ }
      - { name: customer, source_column: CUSTOMER, type: string }
      - { name: quantity, source_column: QUANTITY, type: integer, minimum: 1 }
```

Output is flat — `order_date` from each section's DAY-row is merged
onto every order row from that section. See
[Repeating sections](docs/guides/blocks.md) for the full grammar.

---

## Scattered metadata (anchored layout)

Some cover sheets sprinkle properties at irregular positions. Anchor each
field by the label text near it:

```yaml
entities:
  - name: report
    cardinality: one
    locate: { tab: Cover, orientation: anchored }
    fields:
      - name: period
        type: string
        anchor: { label_match: "Reporting Period", value_at: right, offset: 1 }
      - name: contact_email
        type: email
        anchor: { label_match: "Contact", value_at: right, offset: 1 }
      - name: submitted_on
        type: date
        anchor: { label_match: "Date sent", value_at: right, offset: 1 }
```

Survives the customer adding or removing rows between properties.

---

## Field types and constraints

| Type | Notes |
|---|---|
| `string` | Free text. Add `pattern:` for regex enforcement |
| `integer` | Coerced from int or float-with-no-fractional |
| `number` | int or float |
| `boolean` | Customize with `true_values: [Yes, Y, 1]`, `false_values: [No, N, 0]` |
| `date` | Use `date_format: "%m/%d/%Y"` for ambiguous formats |
| `datetime` | Same |
| `email` | Built-in regex |
| `uuid` | Built-in regex |
| `url` | Built-in regex |

Per-field options:

```yaml
fields:
  - name: customer_email
    source_column: Email
    type: email
    nullable: true                              # blanks allowed
    null_tokens: [N/A, TBD, "-"]                # also treat these strings as null
    normalize: trim                             # trim | lower | trim_lower
```

`null_tokens` is layered: library defaults (`N/A`, `TBD`, `-`, `—`, `(blank)`,
`n/a`, `NaN`) → template-level → field-level. Override any layer, including
setting `null_tokens: []` to disable.

---

## CLI

```bash
# Extract to JSON
crease extract incoming.xlsx --template templates/orders.crease.yml > out.json

# Validate only (exit 0 if valid, 1 if cell-level errors, 2 if structural; tune with --fail-on)
crease validate incoming.xlsx --template templates/orders.crease.yml

# Extract + validate together
crease check incoming.xlsx --template templates/orders.crease.yml --json

# Stream a single entity to JSONL (true streaming, low memory)
crease stream incoming.xlsx --template templates/orders.crease.yml --entity order > orders.jsonl

# Batch over a folder — emits per-file JSON outputs plus an error report
crease batch ./inbox/ --template templates/orders.crease.yml \
  --out ./extracted/ --report ./report.csv

# Run the test corpus (developer command)
crease test test_cases/
```

---

## Installation

```bash
pip install crease                  # core: extract + validate, returns dicts
pip install crease[pandas]          # adds result.to_pandas()
```

Core deps: python-calamine, openpyxl, pydantic, pyyaml. Pandas is an
**optional extra** — if you only use `extract` and `to_pydantic`,
you don't pay for pandas. No LLM, no network calls at runtime.

### Read backends

Crease reads spreadsheets through two interchangeable backends:

| Backend | Formats | When it's used |
|---|---|---|
| **calamine** (default) | `.xlsx`, `.xls`, `.xlsb`, `.ods` | Picked automatically. Fast (Rust under the hood) and GIL-releasing, so a `ThreadPoolExecutor` parallelizes multi-file reads. |
| **openpyxl** | `.xlsx` only | Picked automatically when the template declares `locate.skip_hidden_rows: true` — only openpyxl exposes row-hidden cell metadata. |

Override the auto-selection with `engine="calamine"` or `engine="openpyxl"`
on `extract`, `get`, `stream`, `check`, and `crease.open`. Forcing calamine
on a `skip_hidden_rows` template emits a `UserWarning` and silently
degrades that feature to a no-op (calamine can't see the flag); use this
only when you're reading a non-xlsx file and have already verified hidden
rows aren't present.

### Local development

The repo uses [uv](https://docs.astral.sh/uv/) and the `src/` layout.

```bash
# 1. Clone
git clone git@github.com:dev360/crease.git
cd crease

# 2. Install (core + extras + test deps) into a uv-managed venv
uv sync --all-extras --group test

# 3. Run the corpus
uv run pytest

# 4. Optional: build the docs site locally
uv run mkdocs serve     # http://localhost:8000

# 5. Hook up pre-commit (runs ruff + conventional-commit on every commit)
uv run pre-commit install
uv run pre-commit run --all-files
```

If you're not using uv, plain `pip` works fine against the venv of
your choice. PEP 735 `[dependency-groups]` requires pip ≥ 25.1, so we
install the dev/test tools by name instead:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[pandas]"                       # editable install with the pandas extra
pip install pytest faker pre-commit ruff         # test + dev tools
pytest
```

Template authoring (by hand, by an LLM tool you build, by import from
another schema language) is out of scope for this library.

---

## Errors and validation

Errors are pydantic-shaped — the same vocabulary anyone using Pydantic
already knows. Every constraint declared on a field is enforced at validation
time, with row and field coordinates attached.

```python
report = crease.validate(result, template)

report.is_valid                   # bool — true iff zero errors
report.error_count()              # int
report.errors()                   # list[Error]

err = report.errors()[0]
err.type        # "wrong_type" — stable machine code, safe to route on
err.loc         # ("order", 47, "customer_email") — (entity, row, field)
err.msg         # human-readable
err.input       # the offending value
err.ctx         # extra context, e.g. {"likely_cause": "excel_autoconvert"}
err.severity    # "cell" | "structural"
```

The halt-by-default projection methods raise `crease.ValidationError`, which
carries the same data:

```python
try:
    orders = result.to_pydantic("order", model=Order)
except crease.ValidationError as e:
    e.errors()         # same list as report.errors() would have produced
    e.error_count()
```

### Severity

| Severity | Meaning | What you typically do |
|---|---|---|
| `structural` | The template can't even map the file (missing tab, header mapping failed, column count mismatch). | Bounce back to sender — the file is unusable as-is. |
| `cell` | Per-row problem (missing value, wrong type, constraint violation). | Send to a human review queue with bad rows highlighted, or recover with `allow_partial=True`. |

### Error type codes

**Cell-level** (`severity: "cell"`):

| `error.type` | Triggers when |
|---|---|
| `missing_required` | A non-nullable field has a blank value (after `null_tokens` collapse) |
| `wrong_type` | Value can't coerce to the declared type. Includes `ctx.likely_cause: excel_autoconvert` when applicable |
| `pattern_mismatch` | String doesn't match `pattern:` |
| `enum_violation` | Value not in declared `enum:` |
| `below_minimum`, `above_maximum` | Numeric range violation |
| `empty_row` | Mid-data blank row |
| `duplicate_row` | Row identical to a previous one |
| `anchor_not_found` | Anchored field's label text not present in tab. `ctx.label_was: "absent"`. |
| `anchor_value_blank` | Anchored field's label is present but the value cell is blank. Informational; only fires on `nullable: true` fields. `ctx.label_was: "present"`. |
| `anchor_value_type_mismatch` | Anchor's label matched but the neighbor cell's shape didn't fit `anchor.value_type`. Surfaces the case where the operator put the wrong thing next to the label. |
| `header_duplicated` | `source_column` matches multiple header cells in the same row; bind picked the first. Set `source_column_index:` on the field to choose a specific occurrence (0-indexed across the matches). |
| `header_above_nonblank` | The row immediately above `header_row` has non-blank text in a column that also has a header. Surfaces the case where the operator pointed at the bottom of a two-row header. The column geometry is in `ctx.columns`. |
| `low_data_density` | Entity's `locate.min_data_density` threshold not met across the extracted records. `ctx.density` and `ctx.threshold` carry the numbers. |
| `boolean_alias_unknown` | Value didn't match `true_values`/`false_values` |
| `model_field_missing_in_canonical` | A Pydantic model passed to `to_pydantic` requires a field the template doesn't produce |
| `model_type_mismatch` | A Pydantic model's field type doesn't match the canonical value's type |

**Structural** (`severity: "structural"`):

| `error.type` | Triggers when |
|---|---|
| `missing_tab` | Template's `tab:` doesn't exist |
| `tab_pattern_no_match` | `tab_pattern:` matched zero tabs |
| `column_count_mismatch` | Header row has wrong number of columns |
| `header_mapping_failed` | `source_column`/`source_label` not found |
| `entity_missing` | Locate found nothing |
| `multiple_rows_for_cardinality_one` | `cardinality: one` entity found >1 row |

---

## Documentation

- [`ROADMAP.md`](ROADMAP.md) — what's in v1, what's deferred
- [`COVERAGE.md`](COVERAGE.md) — layouts and validation errors supported
- [`CONVENTIONS.md`](CONVENTIONS.md) — Excel patterns we handle, with examples
- [`test_cases/`](test_cases/) — labeled fixtures that double as the spec

## License

BSD 3-Clause. See [LICENSE](LICENSE).
