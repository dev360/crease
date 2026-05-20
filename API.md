# API — Open Candidates

> **Working doc.** The library's API surface is **not yet locked**. This file
> lists the candidates we've considered, the ones we rejected, and what's
> still up for decision. The current code in `crease/` happens to ship
> **shape A (free functions)** — that's where it landed, not a commitment.
>
> The test corpus (24/24 passing) holds across all live candidates — the
> choice is purely ergonomic. Don't break the corpus while refactoring.

---

## Three live candidates

All three do the same four things; only the entry point differs.

### A. Free functions

```python
import crease

template = crease.Template.load("orders.crease.yml")

result = crease.extract("file.xlsx", template)
report = crease.validate(result, template)
result, report = crease.check("file.xlsx", template)

for order in crease.stream("file.xlsx", template, entity="order"):
    process(order)

with crease.open("file.xlsx", template) as s:
    company = s.get("company")
    for order in s.stream("order"):
        process(company, order)
```

- **Good:** explicit, no magic, mirror of CLI verbs.
- **Bad:** `template` arg passed every call; `crease.open` shadows builtin;
  five top-level names.

### B. Template methods

```python
import crease

template = crease.Template.load("orders.crease.yml")

result = template.extract("file.xlsx")
report = template.validate(result)
result, report = template.check("file.xlsx")

for order in template.stream("file.xlsx", entity="order"):
    process(order)

with template.session("file.xlsx") as s:
    company = s.get("company")
    for order in s.stream("order"):
        process(company, order)
```

- **Good:** one discoverable object; template arg implicit; reads as *"this
  template extracts from this file"*; no builtin shadowing.
- **Bad:** mixes data + behavior on a Pydantic model (Template is already
  domain-specific, so this is a small cost).

### C. File-centric pipeline

```python
import crease

template = crease.Template.load("orders.crease.yml")

sheet = crease.read("file.xlsx").apply(template)
result = sheet.extract()
report = sheet.validate()
result, report = sheet.check()

for order in sheet.records("order"):
    process(order)

company = sheet.one("company")
for order in sheet.records("order"):
    process(company, order)
```

- **Good:** reads left to right like a pipeline; the file is the subject.
- **Bad:** two-step setup; intermediate `SheetSession` object.

---

## Rejected candidates

Documented so we don't relitigate them.

| | Why rejected |
|---|---|
| **D. Schema-as-code (Pydantic-as-template)** — class `Order(BaseModel): ...` is the template | Operators stop being able to edit; templates become Python; conflates schema with code |
| **E. DataFrame-first** — `crease.read_excel(file, template=t, entity="order")` returns a `pd.DataFrame` | Multi-entity files don't fit one DataFrame; validation issues need a side channel; forces pandas on every consumer |
| **Hybrid: YAML template + Pydantic output classes** — `template.extract(file, into=AcmeSales)` | Two schemas drift; Pydantic class can declare fields YAML doesn't emit, or vice versa — no way to keep them honest without lint machinery |

---

## The unresolved insight: output shape depends on workload scale

Whatever entry point we pick (A vs B vs C), the **right output shape is
not the same for every consumer**:

| Consumer | Wants | Why |
|---|---|---|
| **Small data** (web API record, dashboard tile, Django model fill, single-record drop) | Pydantic / typed objects | IDE autocomplete, refactor-safe access, integrates with DRF/FastAPI serializers |
| **Big data** (ETL, analytics, bulk transforms, columnar sinks) | DataFrame *or* JSONL stream | Vectorized ops, columnar storage, pipes to Parquet/DuckDB/Snowflake, memory-bounded |
| **Just-show-me** (one-off script, CLI usage, debugging) | Plain dict | No type machinery; just `result.canonical["orders"][0]["total"]` |

The cleanest way to serve all three: **library returns canonical dicts as the
universal shape**, and provides **opt-in helpers** for the other two:

```python
# canonical dict (always — the universal form)
result = template.extract("file.xlsx")
result.canonical["orders"][0]["total"]      # plain dict

# DataFrame helper for big-data consumers (opt-in)
df = template.extract_df("file.xlsx", entity="order")
df.to_parquet("orders.parquet")

# Pydantic typed access for small-data consumers (DIY in user code, library stays out)
class Order(BaseModel):
    order_id: str
    total: float
orders = [Order.model_validate(r) for r in result.canonical["orders"]]
```

This keeps the library small and shifts shape decisions to the call site,
where the workload context actually lives.

---

## What still needs deciding

1. **Free functions vs Template methods (A vs B).** Both work; pick the
   one that reads better with fresh eyes. (C is a distant third.)
2. **DataFrame helper — library-side or user-side?** Either we ship
   `extract_df(file, entity)` as a convenience or let consumers do
   `pd.DataFrame(result.canonical["orders"])`. Pandas is already a dep so
   there's no install cost; the question is API surface size.
3. **True streaming vs eager-then-iterate?** Today `stream()` is eager
   extract + iterate. For 100k+ row files this defeats the point. True
   row-by-row streaming via openpyxl `read_only=True` is doable but
   requires a separate code path from the pandas-based extractor.
4. **Per-entity work-skipping.** Today `template.extract(file)` does *all*
   entities even if the consumer only wants one. A `get(entity=...)`
   short-circuit would only do the work the caller asked for. Real win for
   big files with multiple tabs.
5. **JSONL — library function or CLI-only?** `crease stream --entity ... >
   out.jsonl` already works via the CLI. A Python `stream_jsonl()` may be
   unnecessary.

---

## File artifacts (stable regardless of API shape)

These are part of the system whichever candidate we pick:

```
*.crease.yml         Template definitions (operator-edited, version-controlled)
extracted JSON       The "canonical" form — entities as top-level keys
report JSON          { verdict, summary, issues[] }
```

### Template

```yaml
template_id: acme_q1
entities:
  - name: company
    cardinality: one
    locate: { tab: Cover, orientation: property_sheet, label_col: 0, value_col: 1 }
    fields:
      - { name: company, source_label: Company, type: string }
      - { name: period,  source_label: Period,  type: string, pattern: ^Q[1-4]\s\d{4}$ }
  - name: order
    cardinality: many
    locate: { tab_pattern: ^Region - (.+)$, orientation: flat, header_row: 3 }
    fields:
      - { name: order_id, source_column: Order ID, type: string, pattern: ^ORD-\d{4}$ }
      - { name: total,    source_column: Total,    type: number, minimum: 0 }
    enrich:
      - { field: region, source: tab_name_regex_group, group: 1 }
ignore_tabs: [Notes]
```

### Extraction output

```json
{
  "template_id": "acme_q1",
  "source_file": "acme_q1_2025.xlsx",
  "errors": [],
  "company": {"company": "Acme Corp", "period": "Q1 2025"},
  "orders":  [{"order_id": "ORD-1001", "total": 14250, "region": "North"}]
}
```

### Validation report

```json
{
  "verdict": "needs_review",
  "summary": "1 missing_required",
  "issues": [
    {"entity": "order", "row": 47, "field": "customer_email", "reason": "missing_required"}
  ]
}
```

---

## Pydantic models that ARE stable (the YAML schema)

These models define the YAML grammar — they don't change with the API
candidate.

```python
class Template(BaseModel):
    template_id: str
    version: int = 1
    description: str
    entities: list[Entity]
    ignore_tabs: list[str] = []
    notes: list[str] = []
    null_tokens: list[str] | None = None
    filename_pattern: str | None = None
    filename_capture: list[FilenameCapture] = []

class Entity(BaseModel):
    name: str
    cardinality: Literal["one", "many"]
    locate: Locate
    fields: list[FieldSpec]
    enrich: list[Enrich] = []
    unpivot: Unpivot | None = None

class Locate(BaseModel):
    tab: str | None = None
    tab_pattern: str | None = None
    orientation: Literal["flat", "property_sheet", "anchored"]
    cell_range: str | None = None
    header_row: int = 0
    header_anchor: HeaderAnchor | None = None
    data_starts_row: int | None = None
    data_ends_at: DataEnd | None = None
    label_col: int = 0
    value_col: int = 1
    start_row: int = 0
    skip_hidden_rows: bool = False

class FieldSpec(BaseModel):
    name: str
    type: Literal["string", "integer", "number", "boolean", "date", "datetime", "email", "uuid", "url"]
    source_column: str | None = None
    source_label: str | None = None
    anchor: Anchor | None = None
    pattern: str | None = None
    enum: list[str] | None = None
    minimum: float | None = None
    maximum: float | None = None
    nullable: bool = False
    null_tokens: list[str] | None = None
    normalize: Literal["none", "trim", "lower", "trim_lower"] = "none"
    treat_as_text: bool = False
    true_values: list[str] | None = None
    false_values: list[str] | None = None
    date_format: str | None = None
```

---

## Error vocabulary (stable)

Cell-level (→ `needs_review`):
`missing_required`, `wrong_type`, `pattern_mismatch`, `enum_violation`,
`below_minimum`, `above_maximum`, `empty_row`, `duplicate_row`,
`anchor_not_found`, `boolean_alias_unknown`.

Structural (→ `reject`):
`missing_tab`, `tab_pattern_no_match`, `column_count_mismatch`,
`header_mapping_failed`, `entity_missing`,
`multiple_rows_for_cardinality_one`, `unsupported_orientation`.

---

## What the API is NOT, regardless of shape

- No "auto-fix" — we flag, we don't modify the file
- No template authoring inside this library — templates are authored
  elsewhere (by hand, by an LLM tool you build, by import from another
  schema language)
- No persistence layer — templates are git-managed YAML files
- No customer/template router — which template applies to which file is
  the caller's problem (filename convention, intake endpoint, etc.)
- No editing the input file
