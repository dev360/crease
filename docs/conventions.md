# Excel conventions in the wild

A reference for the patterns customers actually send. Each section names a
behaviour we've seen, why it breaks downstream code, and how crease
handles it.

!!! note "Work in progress"
    The full catalogue currently lives in
    [`CONVENTIONS.mdx`](https://github.com/dev360/crease/blob/main/CONVENTIONS.mdx)
    (which uses interactive React components for the grid examples).
    A rendered version for this docs site is being prepared.

## What's covered

- Header normalization (trailing spaces, smart quotes, casing)
- Null tokens (`N/A`, `TBD`, `-`, `—`, `(blank)` and friends)
- Excel autoconvert (`SEPT2` → date, `2310009E13` → scientific)
- Soft-deleted rows hidden but not removed
- Title rows above the table header
- Cover-tab `[label, value]` property sheets
- Anchored cells with labels at arbitrary positions
- Multi-tab files with one entity per region
- Wide-format columns that should be unpivoted

The [`test_cases/`](https://github.com/dev360/crease/tree/main/test_cases)
directory has a labelled fixture for each — the input xlsx, the gold
template, the expected canonical JSON, and the expected validation
errors.
