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
