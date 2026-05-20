# Pydantic projection

`result.to_pydantic("entity", model=...)` projects canonical records into
Pydantic model instances. Two modes:

## Bring your own model

Useful when the downstream pipeline already has a Pydantic model and you
just want to fit the extracted data into it.

```python
from pydantic import BaseModel

class Order(BaseModel):
    order_id: str
    quantity: int

orders = result.to_pydantic("order", model=Order)
```

**Field matching is opportunistic by attribute name.** Fields the model
doesn't declare are dropped silently; only the fields you care about are
populated.

| Situation | Behaviour |
|---|---|
| Model has field, canonical has it, types match | Carries over |
| Model has field, canonical has it, types mismatch | Raises `crease.ValidationError` |
| Model has required field, canonical doesn't | Raises `crease.ValidationError` |
| Model doesn't have field, canonical has it | Silently dropped |

## Auto-generated model

If you don't pass `model=`, crease builds one from the template's field
declarations:

```python
orders = result.to_pydantic("order")    # uses Template.model("order")
```

This is useful for one-off scripts and notebooks where the template is
already the source of truth. The generated model uses
`ConfigDict(extra="ignore", strict=False, arbitrary_types_allowed=True)`
— it accepts Pydantic's safe coercions (ISO date strings → `date`, `"5"`
→ `5`) and ignores extra keys, but rejects truly incompatible types.

## Halt by default, opt-in to partial

Both modes **halt** when the report has errors:

```python
try:
    orders = result.to_pydantic("order", model=Order)
except crease.ValidationError as e:
    e.errors()                  # full error list
```

Pass `allow_partial=True` to recover what you can:

```python
orders = result.to_pydantic("order", model=Order, allow_partial=True)
# rows that didn't project are absent from `orders`;
# they're listed in result.report.errors()
```
