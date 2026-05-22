"""Tab matching, cell-range parsing, and header-anchor scanning."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from crease._coerce import normalize_header
from crease._workbook import Sheet, Workbook
from crease.template_model import HeaderAnchor, Locate


@dataclass
class TabMatch:
    worksheet: Sheet
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


def find_tabs(workbook: Workbook, locate: Locate, ignore_tabs: list[str]) -> list[TabMatch]:
    """Return all worksheets matching this locate spec."""
    candidates = [ws for ws in workbook.sheets if ws.name not in ignore_tabs]
    # ``tab: only`` is a sentinel for single-data-tab workbooks where the
    # tab's name varies per file (operators often name it the date). Bind
    # to the lone non-ignored sheet regardless of its name.
    if locate.tab == "only":
        if len(candidates) == 1:
            ws = candidates[0]
            return [TabMatch(worksheet=ws, name=ws.name, regex_match=None)]
        return []
    matches: list[TabMatch] = []
    for ws in candidates:
        if locate.tab is not None and ws.name == locate.tab:
            matches.append(TabMatch(worksheet=ws, name=ws.name, regex_match=None))
        elif locate.tab_pattern is not None:
            m = re.match(locate.tab_pattern, ws.name)
            if m:
                matches.append(TabMatch(worksheet=ws, name=ws.name, regex_match=m))
    return matches


def find_header_row(
    ws: Sheet,
    anchor: HeaderAnchor,
    max_rows_to_scan: int = 50,
    *,
    min_row: int = 0,
    max_row: int | None = None,
) -> int | None:
    """Scan for the first row containing the anchor text. Returns 0-indexed row.

    `min_row` / `max_row` (0-indexed, inclusive) scope the search to a window
    of the worksheet — used when an entity lives inside a `Block` instance so
    its header anchor is restricted to that instance's row range.
    """
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

    # iter_rows is 1-indexed in this codebase's adapter, scan caps are inclusive.
    iter_min_row = min_row + 1
    iter_max_row = (max_row + 1) if max_row is not None else max_rows_to_scan
    for offset, row in enumerate(ws.iter_rows(min_row=iter_min_row, max_row=iter_max_row)):
        r_idx = min_row + offset
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


def resolve_header_row(
    ws: Sheet,
    locate: Locate,
    *,
    min_row: int = 0,
    max_row: int | None = None,
) -> int:
    """Anchor wins if set; otherwise the literal `header_row`.

    When `min_row` / `max_row` are set (block-scoped extraction), the
    anchor scan is restricted to that window, and the literal
    `locate.header_row` is interpreted relative to `min_row`.
    """
    if locate.header_anchor is not None:
        found = find_header_row(ws, locate.header_anchor, min_row=min_row, max_row=max_row)
        if found is None:
            raise ValueError(f"header_anchor {locate.header_anchor.text!r} not found in tab {ws.name!r}")
        return found
    return min_row + locate.header_row


def hidden_row_indices(ws: Sheet) -> set[int]:
    """0-indexed set of hidden row indices. Empty when the backend can't tell."""
    return ws.hidden_row_indices()


def normalize_headers(headers: list[Any]) -> list[str]:
    return [normalize_header(h) for h in headers]
