"""
Corruptors mutate a Sheet (2D grid) and return a label describing
what was broken. They are layout-agnostic — the generator decides
which cells/rows are valid targets per layout.

Each corruptor is pure: same inputs → same outputs.
"""

import random
from dataclasses import dataclass, field
from typing import Any

from sheet import Sheet, copy, n_cols


@dataclass
class CorruptionResult:
    sheet: Sheet
    label: dict[str, Any] = field(default_factory=dict)


# ---------- cell-level ----------


def drop_cell(sheet: Sheet, r: int, c: int) -> CorruptionResult:
    out = copy(sheet)
    out[r][c] = None
    return CorruptionResult(
        out,
        {
            "verdict": "needs_review",
            "bad_cells": [[r, c]],
            "reason": "missing_value",
        },
    )


def wrong_dtype(sheet: Sheet, r: int, c: int, value: Any = "N/A") -> CorruptionResult:
    out = copy(sheet)
    out[r][c] = value
    return CorruptionResult(
        out,
        {
            "verdict": "needs_review",
            "bad_cells": [[r, c]],
            "reason": "wrong_dtype",
            "details": {"value": value},
        },
    )


def rename_label(sheet: Sheet, r: int, c: int, new_value: str = "UNKNOWN_LABEL") -> CorruptionResult:
    """Overwrite a label/header cell with an unexpected value."""
    out = copy(sheet)
    original = out[r][c]
    out[r][c] = new_value
    return CorruptionResult(
        out,
        {
            "verdict": "reject",
            "bad_cells": [[r, c]],
            "reason": "header_renamed",
            "details": {"from": original, "to": new_value},
        },
    )


# ---------- row-level ----------


def blank_row(sheet: Sheet, r: int) -> CorruptionResult:
    out = copy(sheet)
    out[r] = [None] * n_cols(out)
    return CorruptionResult(
        out,
        {
            "verdict": "needs_review",
            "bad_rows": [r],
            "reason": "empty_row",
        },
    )


def shift_row_left(sheet: Sheet, r: int, n: int = 1) -> CorruptionResult:
    out = copy(sheet)
    width = n_cols(out)
    vals = (out[r] + [None] * width)[:width]  # pad to full width
    shifted = vals[n:] + [None] * n
    out[r] = shifted
    return CorruptionResult(
        out,
        {
            "verdict": "needs_review",
            "bad_rows": [r],
            "reason": "shifted_left",
            "details": {"n": n},
        },
    )


def shift_block_down(sheet: Sheet, start_r: int, n: int = 1) -> CorruptionResult:
    out = copy(sheet)
    width = n_cols(out)
    blanks = [[None] * width for _ in range(n)]
    out = out[:start_r] + blanks + out[start_r:]
    return CorruptionResult(
        out,
        {
            "verdict": "needs_review",
            "bad_rows": list(range(start_r, start_r + n)),
            "reason": "block_shifted_down",
        },
    )


def duplicate_row(sheet: Sheet, r: int) -> CorruptionResult:
    out = copy(sheet)
    out = out[: r + 1] + [list(out[r])] + out[r + 1 :]
    return CorruptionResult(
        out,
        {
            "verdict": "needs_review",
            "bad_rows": [r + 1],
            "reason": "duplicate_row",
        },
    )


# ---------- column-level ----------


def drop_column(sheet: Sheet, c: int) -> CorruptionResult:
    out = [row[:c] + row[c + 1 :] for row in sheet]
    return CorruptionResult(
        out,
        {
            "verdict": "reject",
            "bad_cells": [],
            "reason": "missing_column",
            "details": {"col_index": c},
        },
    )


def swap_columns(sheet: Sheet, c_a: int, c_b: int) -> CorruptionResult:
    out = copy(sheet)
    for row in out:
        if c_a < len(row) and c_b < len(row):
            row[c_a], row[c_b] = row[c_b], row[c_a]
    return CorruptionResult(
        out,
        {
            "verdict": "reject",
            "bad_cells": [],
            "reason": "columns_swapped",
            "details": {"a": c_a, "b": c_b},
        },
    )


# ---------- dispatch ----------


def apply(kind: str, sheet: Sheet, layout, rng: random.Random) -> CorruptionResult:
    """Apply a named corruption, picking valid coords for the given layout."""
    data_cells = layout.data_cells(sheet)
    label_cells = layout.label_cells(sheet)
    data_rows = layout.data_rows(sheet)

    if kind == "drop_cell":
        r, c = rng.choice(data_cells)
        return drop_cell(sheet, r, c)

    if kind == "wrong_dtype":
        r, c = rng.choice(data_cells)
        return wrong_dtype(sheet, r, c)

    if kind == "rename_label":
        r, c = rng.choice(label_cells)
        return rename_label(sheet, r, c)

    if kind == "blank_row":
        return blank_row(sheet, rng.choice(data_rows))

    if kind == "shift_row_left":
        return shift_row_left(sheet, rng.choice(data_rows), n=rng.randint(1, 2))

    if kind == "shift_block_down":
        start = rng.choice(data_rows)
        return shift_block_down(sheet, start, n=rng.randint(1, 3))

    if kind == "duplicate_row":
        return duplicate_row(sheet, rng.choice(data_rows))

    if kind == "drop_column":
        # avoid dropping the label column (col 0) on property_sheet — it would
        # leave a sheet with only values and no schema signal. Drop a data col.
        c = rng.randrange(n_cols(sheet))
        return drop_column(sheet, c)

    if kind == "swap_columns":
        width = n_cols(sheet)
        a, b = rng.sample(range(width), 2)
        return swap_columns(sheet, a, b)

    raise ValueError(f"unknown corruption kind: {kind}")
