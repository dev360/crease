# CLI

`pip install crease` puts a `crease` command on your PATH.

## Commands

```bash
# Extract to JSON
crease extract incoming.xlsx --template templates/orders.crease.yml > out.json

# Validate only — non-zero exit on errors at or above --fail-on
crease validate incoming.xlsx --template templates/orders.crease.yml \
  --fail-on structural

# Extract + validate together
crease check incoming.xlsx --template templates/orders.crease.yml --compact

# Stream a single entity to JSONL
crease stream incoming.xlsx --template templates/orders.crease.yml --entity order \
  > orders.jsonl

# Batch over a folder — per-file JSON outputs plus an aggregated report
crease batch ./inbox/ --template templates/orders.crease.yml \
  --out ./extracted/ --report ./report.json
```

## Exit codes for `crease validate`

| `--fail-on` | Exit 0 | Exit 1 | Exit 2 |
|---|---|---|---|
| `none` (default off) | any verdict | — | — |
| `cell` | only when fully valid | cell-level errors only | any structural errors |
| `structural` (default) | no structural errors | — | any structural errors |

## JSON output

`crease validate --json` and `crease check` emit a structured report:

```json
{
  "is_valid": false,
  "error_count": 3,
  "errors": [
    {
      "type": "wrong_type",
      "loc": ["order", 47, "quantity"],
      "msg": "Field 'quantity' could not be coerced to integer",
      "input": "twelve",
      "ctx": {"expected": "integer"}
    }
  ]
}
```

The `type` field is a stable machine code suitable for downstream
routing.
