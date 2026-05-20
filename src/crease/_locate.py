"""Tab matching, cell-range parsing, and header-anchor scanning."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from openpyxl.worksheet.worksheet import Worksheet

from crease._coerce import normalize_header
from crease.template_model import HeaderAnchor, Locate


@dataclass
class TabMatch:
    worksheet: Any
    name: str
    regex_match: re.Match | None  # set when matched via tab_pattern


@dataclass
class CellRange:
    start_row: int  # 0-indexed, inclusive
    end_row: int | None  # 0-indexed, inclusive; None = end-of-sheet
    start_col: int  # 0-indexed, inclusive
    end_col: int | None  # 0-indexed, inclusive; None = end-of-sheet


_RANGE_RE = re.compile(
    r"^([A-Z]+)(\d+):([A-Z*]+)(\d+|\*)$",
    re.I,
)


def col_to_index(col: str) -> int:
    """A → 0, B → 1, AA → 26."""
    result = 0
    for c in col.upper():
        result = result * 26 + (ord(c) - ord("A") + 1)
    return result - 1


def parse_cell_range(s: str) -> CellRange:
    m = _RANGE_RE.match(s.strip())
    if not m:
        raise ValueError(f"invalid cell_range: {s!r}")
    sc, sr, ec, er = m.groups()
    return CellRange(
        start_row=int(sr) - 1,
        end_row=None if er == "*" else int(er) - 1,
        start_col=col_to_index(sc),
        end_col=None if ec == "*" else col_to_index(ec),
    )


def find_tabs(workbook, locate: Locate, ignore_tabs: list[str]) -> list[TabMatch]:
    """Return all worksheets matching this locate spec."""
    matches: list[TabMatch] = []
    for ws in workbook.worksheets:
        if ws.title in ignore_tabs:
            continue
        if locate.tab is not None and ws.title == locate.tab:
            matches.append(TabMatch(worksheet=ws, name=ws.title, regex_match=None))
        elif locate.tab_pattern is not None:
            m = re.match(locate.tab_pattern, ws.title)
            if m:
                matches.append(TabMatch(worksheet=ws, name=ws.title, regex_match=m))
    return matches


def find_header_row(ws: Worksheet, anchor: HeaderAnchor, max_rows_to_scan: int = 50) -> int | None:
    """Scan for the first row containing the anchor text. Returns 0-indexed row."""
    target = anchor.text
    mode = anchor.match_mode

    def matches(s: str) -> bool:
        s = s.strip()
        if mode == "exact":
            return s == target
        if mode == "contains":
            return target in s
        if mode == "regex":
            return bool(re.search(target, s))
        return False

    for r_idx, row in enumerate(ws.iter_rows(values_only=True, max_row=max_rows_to_scan)):
        cells = list(row)
        if anchor.column is not None:
            if anchor.column < len(cells) and cells[anchor.column] is not None:
                if matches(str(cells[anchor.column])):
                    return r_idx
        else:
            for c in cells:
                if c is not None and matches(str(c)):
                    return r_idx
    return None


def resolve_header_row(ws: Worksheet, locate: Locate) -> int:
    """Anchor wins if set; otherwise the literal `header_row`."""
    if locate.header_anchor is not None:
        found = find_header_row(ws, locate.header_anchor)
        if found is None:
            raise ValueError(f"header_anchor {locate.header_anchor.text!r} not found in tab {ws.title!r}")
        return found
    return locate.header_row


def hidden_row_indices(ws: Worksheet) -> set[int]:
    """0-indexed set of hidden row indices."""
    hidden: set[int] = set()
    for r_idx, dim in ws.row_dimensions.items():
        if dim.hidden:
            # openpyxl uses 1-indexed rows
            hidden.add(r_idx - 1)
    return hidden


def normalize_headers(headers: list[Any]) -> list[str]:
    return [normalize_header(h) for h in headers]
