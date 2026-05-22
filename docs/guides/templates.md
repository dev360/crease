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
