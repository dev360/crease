"""
A Sheet is a 2D grid of cells — list[list[Any]]. This is the common
intermediate representation. Layouts produce sheets; corruptors mutate
sheets; the writer dumps a sheet to xlsx.

Rows may have differing widths in principle, but layout renderers
always produce rectangular sheets.
"""
from pathlib import Path
from typing import Any

import openpyxl

Sheet = list[list[Any]]


def n_rows(sheet: Sheet) -> int:
    return len(sheet)


def n_cols(sheet: Sheet) -> int:
    return max((len(r) for r in sheet), default=0)


def copy(sheet: Sheet) -> Sheet:
    return [list(row) for row in sheet]


def write_xlsx(sheet: Sheet, path: Path) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in sheet:
        ws.append(list(row))
    wb.save(path)
