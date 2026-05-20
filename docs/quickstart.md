# Quick start

This page walks the three-step flow end to end: **extract → validate →
project**. Each step does one thing.

## 1. Install

```bash
pip install crease
```

For the pandas projection adapter:

```bash
pip install crease[pandas]
```

## 2. Author a template

A template lives next to your code (or in a templates repo). It describes
*where* the data lives in the xlsx and *what* the fields mean.

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

The `pattern:`, `minimum:`, `type:` fields are **both** coercion hints for
the extractor and constraints for the validator.

## 3. Extract

```python
import crease

template = crease.Template.load("templates/orders.crease.yml")
result = crease.extract("incoming.xlsx", template)

result.canonical["orders"][0]
# {"order_id": "ORD-1001", "customer_email": "a@acme.com",
#  "order_date": "2025-01-15", "quantity": 10, "unit_price": 25.50}
```

`result.canonical` is a plain dict. No pandas or pydantic imported yet.

## 4. Validate

```python
report = crease.validate(result, template)

report.is_valid             # bool — the 90% check
report.error_count()        # int
report.errors()             # list[Error]
report.has_structural       # any structural errors? (template can't even map the file)

for err in report.errors():
    print(err.type, err.loc, err.msg)
```

Or do extract + validate in one call:

```python
result, report = crease.check("incoming.xlsx", template)
```

## 5. Project

Three ways to get the data out, all opt-in:

=== "Pydantic"

    ```python
    from pydantic import BaseModel

    class Order(BaseModel):
        order_id: str
        quantity: int      # only the fields you care about

    orders = result.to_pydantic("order", model=Order)
    ```

    Field matching is **opportunistic by attribute name**: canonical fields
    that the model doesn't declare are dropped silently. Type mismatches
    raise `crease.ValidationError`.

=== "Pandas"

    ```python
    df = result.to_pandas("order")
    ```

    Requires `pip install crease[pandas]`.

=== "Iterate as dicts"

    ```python
    for order in result.iter("order"):
        pipeline.send(order)
    ```

## 6. Handle errors

The projection methods **halt by default** if the report has any errors —
the library's whole pitch is "fail loudly with coordinates":

```python
try:
    orders = result.to_pydantic("order", model=Order)
except crease.ValidationError as e:
    e.errors()                  # same shape as report.errors()
    e.error_count()
```

To opportunistically recover and keep the rows that *did* map cleanly:

```python
orders = result.to_pydantic("order", model=Order, allow_partial=True)
# rows that didn't validate are absent from orders;
# they're listed in result.report.errors() with row coordinates.
```

## Where next

- [Why crease](why.md) — the failure modes that shaped these defaults.
- [Templates guide](guides/templates.md) — authoring richer templates.
- [Pydantic projection](guides/pydantic-projection.md) — model rules,
  opportunistic matching, `allow_partial`.
- [API reference](reference/extract.md) — full docstring-driven docs.
