# Streaming large files

For multi-hundred-thousand-row files, stream instead of materializing.
Streaming takes the same `model=` and `allow_partial=` arguments as the
materialized projections, so the API shape stays symmetric.

```python
# Yields dicts
for order in crease.stream("big.xlsx", template, entity="order"):
    pipeline.send(order)

# Yields validated Pydantic instances
for order in crease.stream("big.xlsx", template, entity="order", model=Order):
    pipeline.send(order)
```

## Errors flow through the report, not the iterator

The iterator returns the **happy path**. Problems land on the session's
report and can be inspected after consumption:

```python
with crease.open("big.xlsx", template) as session:
    for order in session.stream("order", model=Order, allow_partial=True):
        pipeline.send(order)

    if not session.report().is_valid:
        log.warning(session.report().errors())
```

!!! note "Implementation note"
    In v1, `crease.stream` and `Session.stream` materialise the result
    internally and yield from it. True row-by-row streaming via openpyxl's
    read-only mode is a follow-on once the eager extraction path is
    proven.
