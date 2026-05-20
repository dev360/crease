# Errors

Crease's error model is pydantic-shaped: every problem the library
surfaces — whether structural (template can't map the file) or cell-level
(a value violated a constraint) — is represented as the same `Error`
type, with the same five fields.

## ::: crease.Error
    options:
      members:
        - type
        - loc
        - msg
        - input
        - ctx
        - severity
        - is_structural
        - is_cell
        - to_dict

## ::: crease.ValidationError
    options:
      members:
        - errors
        - error_count

## Error type taxonomy

The `error.type` field is a stable machine code safe to route on. The
full taxonomy is in the [README's error table](https://github.com/dev360/crease#error-type-codes).
