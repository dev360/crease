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

### `blocks:` grammar (v2)

These extract-time codes fire when the [`blocks:`](../guides/blocks.md)
grammar can't make sense of a file. All are `severity: structural`.

| `error.type` | Fires when… |
|---|---|
| `block_starts_not_found` | A tab matches the block's `tab_pattern` but no cell matches `starts_at` anywhere in the configured column. |
| `block_unterminated` | `ends_at` is configured but no candidate row fires before the next `starts_at` match or EOF. |
| `capture_no_match` | A capture with `required: true` matches zero cells inside a block instance. |
| `capture_multiple_matches` | A capture with `on_multiple: error` matches more than one cell inside a block instance. |
| `block_ref_not_found` | An entity's `block:` field names a block that isn't declared in `template.blocks`. Surfaced at `Template.model_validate` time. |

A capture whose value matches the regex but fails to coerce to the
declared `type` (e.g. `type: date` with a value that doesn't fit any
of `date_formats`) emits the existing `wrong_type` code, keyed to the
capture field.
