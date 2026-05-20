"""
Layouts turn records (or crosstab data) into Sheets.

Four layouts so far:
  - flat:           header row, then data rows                  (most common)
  - transposed:     headers in row 0, single value row in row 1 (one record)
  - property_sheet: each row is [label | value]                 (one record)
  - crosstab:       [blank][col_dim_1][col_dim_2]...            (matrix data)
                    [row_label][value][value]...

Each layout knows:
  - how to render
  - which corruption kinds apply to it
  - where "label" cells live (for label-targeted corruptions)
  - where "data" cells live (for value-targeted corruptions)
"""
from dataclasses import dataclass
from typing import Callable
import random

from series import Series, CrosstabSeries
from sheet import Sheet


@dataclass
class Layout:
    name: str
    applicable_corruptions: list[str]
    label_cells: Callable[[Sheet], list[tuple[int, int]]]
    data_cells:  Callable[[Sheet], list[tuple[int, int]]]
    data_rows:   Callable[[Sheet], list[int]]


# ---------- flat ----------

def render_flat(series: Series, n_records: int, rng: random.Random) -> Sheet:
    sheet: Sheet = [list(series.columns)]
    for record in series.make_records(n_records):
        sheet.append([record[c] for c in series.columns])
    return sheet


def _flat_label_cells(sheet: Sheet) -> list[tuple[int, int]]:
    return [(0, c) for c in range(len(sheet[0]))]


def _flat_data_cells(sheet: Sheet) -> list[tuple[int, int]]:
    return [(r, c) for r in range(1, len(sheet)) for c in range(len(sheet[0]))]


def _flat_data_rows(sheet: Sheet) -> list[int]:
    return list(range(1, len(sheet)))


# ---------- transposed (header row + single value row) ----------

def render_transposed(series: Series, n_records: int, rng: random.Random) -> Sheet:
    record = series.make_record()
    return [list(series.columns), [record[c] for c in series.columns]]


def _transposed_label_cells(sheet: Sheet) -> list[tuple[int, int]]:
    return [(0, c) for c in range(len(sheet[0]))]


def _transposed_data_cells(sheet: Sheet) -> list[tuple[int, int]]:
    return [(1, c) for c in range(len(sheet[0]))]


def _transposed_data_rows(sheet: Sheet) -> list[int]:
    return [1]


# ---------- property_sheet (each row is [label, value]) ----------

def render_property_sheet(series: Series, n_records: int, rng: random.Random) -> Sheet:
    record = series.make_record()
    return [[c, record[c]] for c in series.columns]


def _property_label_cells(sheet: Sheet) -> list[tuple[int, int]]:
    return [(r, 0) for r in range(len(sheet))]


def _property_data_cells(sheet: Sheet) -> list[tuple[int, int]]:
    return [(r, 1) for r in range(len(sheet))]


def _property_data_rows(sheet: Sheet) -> list[int]:
    return list(range(len(sheet)))


# ---------- crosstab ----------

def render_crosstab(spec: CrosstabSeries, rng: random.Random) -> Sheet:
    sheet: Sheet = [[spec.corner_label] + list(spec.col_labels)]
    for _ in range(spec.n_row_labels):
        row_label = spec.row_label_factory()
        values = [spec.value_factory() for _ in spec.col_labels]
        sheet.append([row_label] + values)
    return sheet


def _crosstab_label_cells(sheet: Sheet) -> list[tuple[int, int]]:
    # column headers (row 0, cols >= 1) + row headers (rows >= 1, col 0)
    col_headers = [(0, c) for c in range(1, len(sheet[0]))]
    row_headers = [(r, 0) for r in range(1, len(sheet))]
    return col_headers + row_headers


def _crosstab_data_cells(sheet: Sheet) -> list[tuple[int, int]]:
    return [(r, c) for r in range(1, len(sheet)) for c in range(1, len(sheet[0]))]


def _crosstab_data_rows(sheet: Sheet) -> list[int]:
    return list(range(1, len(sheet)))


# ---------- registry ----------

# Corruption kinds available, mapped to layouts that support them.
# "rename_label" means "rename a cell that contains a field-name/label".
# "drop_label_column" means "remove a whole column whose role is labels".
# Layouts opt in by listing the corruption kinds they accept.

LAYOUTS: dict[str, Layout] = {
    "flat": Layout(
        name="flat",
        applicable_corruptions=[
            "drop_cell", "blank_row", "shift_row_left", "shift_block_down",
            "wrong_dtype", "duplicate_row", "drop_column", "rename_label",
            "swap_columns",
        ],
        label_cells=_flat_label_cells,
        data_cells=_flat_data_cells,
        data_rows=_flat_data_rows,
    ),
    "transposed": Layout(
        name="transposed",
        applicable_corruptions=[
            "drop_cell", "wrong_dtype", "rename_label", "shift_row_left",
            "drop_column",
        ],
        label_cells=_transposed_label_cells,
        data_cells=_transposed_data_cells,
        data_rows=_transposed_data_rows,
    ),
    "property_sheet": Layout(
        name="property_sheet",
        applicable_corruptions=[
            "drop_cell", "blank_row", "wrong_dtype", "rename_label",
            "duplicate_row", "shift_block_down",
        ],
        label_cells=_property_label_cells,
        data_cells=_property_data_cells,
        data_rows=_property_data_rows,
    ),
    "crosstab": Layout(
        name="crosstab",
        applicable_corruptions=[
            "drop_cell", "blank_row", "shift_row_left", "shift_block_down",
            "wrong_dtype", "duplicate_row", "drop_column", "rename_label",
            "swap_columns",
        ],
        label_cells=_crosstab_label_cells,
        data_cells=_crosstab_data_cells,
        data_rows=_crosstab_data_rows,
    ),
}
