# Pandas projection

`result.to_pandas("entity")` returns a pandas DataFrame.

## Install

Pandas is **not** a core dependency. Install the extra:

```bash
pip install crease[pandas]
```

The pandas import is deferred until `to_pandas` is actually called, so
users who never project to a DataFrame don't pay the import cost.

## Usage

```python
df = result.to_pandas("order")
```

For `cardinality: one` entities, you get a one-row DataFrame.

## Halt-by-default

Like the other projection methods, `to_pandas` raises
`crease.ValidationError` if the report has any errors. Pass
`allow_partial=True` to recover whatever was extracted:

```python
df = result.to_pandas("order", allow_partial=True)
```
