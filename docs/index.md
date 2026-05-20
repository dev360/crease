# crease

Declarative Excel-to-JSON extraction **and** validation. Apply a compact
YAML template to a spreadsheet — `.xlsx`, `.xls`, `.xlsb`, or `.ods` — get
canonical JSON out plus structured per-cell errors. No spreadsheet-specific
code in your pipeline.

```bash
pip install crease
```

!!! note "Multi-format reads, single API"
    Calamine is the default read backend, so the same `extract()` call
    works on `.xlsx`, `.xls`, `.xlsb`, and `.ods`. Openpyxl is kept as a
    fallback for templates that need `locate.skip_hidden_rows` — picked
    automatically. See [Read backends](#read-backends) for the auto-selection
    rules.

## The 30-second pitch

A template describes *where* the data lives and *what* the fields mean.
The same template drives both extraction and validation:

```python
import crease

template = crease.Template.load("templates/orders.crease.yml")

# 1. Extract — turn cells into canonical JSON
result = crease.extract("incoming.xlsx", template)

# 2. Validate — independent inspection step
report = crease.validate(result, template)
report.is_valid                    # bool
report.errors()                    # list[Error] — pydantic-shaped

# 3. Project — get the data in whatever shape you want
from pydantic import BaseModel

class Order(BaseModel):
    order_id: str
    quantity: int

orders = result.to_pydantic("order", model=Order)
df     = result.to_pandas("order")    # requires crease[pandas]
for o  in result.iter("order"):
    pipeline.send(o)
```

## Design principles

1. **Fail loudly with coordinates.** Every problem the library surfaces
   carries a row and field — `Error.loc = (entity, row, field)` — so
   downstream systems can route on it. Nothing is silently swallowed into
   the canonical output.

2. **Pydantic-native vocabulary.** Errors, validation, and projection
   reuse the names a Python developer already knows from Pydantic:
   `ValidationError`, `errors()`, `error_count()`, `loc`, `type`, `msg`,
   `input`, `ctx`. No bespoke terminology where a standard one fits.

3. **No surprise dependencies.** `crease.extract` returns a plain dict —
   pandas is only imported when `to_pandas` is actually called. Install
   `pip install crease` and pay for nothing you don't use.

4. **Templates are the spec.** A template is the *only* thing that
   changes when a new vendor sends you a slightly different file. The
   pipeline code that consumes the canonical output stays the same.

## Read backends

Reads go through one of two interchangeable backends. Auto-selection
covers the common case; the `engine=` kwarg is the manual escape hatch.

| Backend | Formats | When it's used |
|---|---|---|
| **calamine** (default) | `.xlsx`, `.xls`, `.xlsb`, `.ods` | Picked automatically. Faster (Rust) and GIL-releasing, so multi-file workloads parallelize with a thread pool. |
| **openpyxl** | `.xlsx` only | Picked automatically when a template declares `locate.skip_hidden_rows: true` — only openpyxl exposes the row-hidden flag. |

```python
# default — calamine auto-selected unless the template needs hidden-row metadata
crease.extract("orders.xls", template)

# force the backend; same kwarg on extract / check / stream / open
crease.extract("orders.xlsx", template, engine="openpyxl")
```

## Where to go next

- [Why crease](why.md) — the documented failure modes (gene-name
  autoconvert, the Public Health England COVID overflow, the JPMorgan VaR
  copy-paste, others) that motivated each feature.
- [Quick start](quickstart.md) — the minimal extract → validate → project
  loop end-to-end.
- [Reference](reference/extract.md) — auto-generated API documentation
  from docstrings.
- [Conventions](conventions.md) — the Excel patterns crease knows how to
  handle.
