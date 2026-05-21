"""Failing tests for CSV-format edges (companion to test_field_scan_gaps.py).

These tests assume the design call ``handle CSV interchangeably with Excel``
has landed. They encode the format-specific edges that surface once CSV is
accepted as a source: thousand separators, percent strings, BOM in the
first header cell, delimiter sniffing, embedded newlines in quoted cells,
encoding fallback.

Proposed API surface for CSV (used by every test below):

- ``locate.source: csv`` opts a Locate into the CSV reader (default
  remains the xlsx/calamine path; existing templates unaffected).
- A template-level ``csv:`` block carries reader options
  (``delimiter: auto | "," | ";" | "\\t"``, ``encoding: auto | "utf-8" |
  "windows-1252" | ...``, ``quote: '"'``).
- Per-field ``number_format: thousands | percent | currency`` opt-in
  coerces the string-encoded numbers that xlsx would have given as
  native types. Default remains strict ("fail loudly with coordinates").
- CSV duplicate columns are not retested here — the same
  ``header_duplicated`` warning from P1-2 applies once the CSV reader
  feeds the same ``_extract_flat`` path.

All data is fictitious. No real customer values cross into this repo.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from crease import Template, extract, validate

# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------


def _csv(
    tmp_path: Path,
    content: str | bytes,
    *,
    name: str = "input.csv",
    encoding: str = "utf-8",
) -> Path:
    """Write a CSV file (text or pre-encoded bytes) and return the path."""
    path = tmp_path / name
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding=encoding)
    return path


def _yml(tmp_path: Path, body: str, *, name: str = "template.yml") -> Path:
    path = tmp_path / name
    path.write_text(textwrap.dedent(body).strip() + "\n")
    return path


def _load(tmp_path: Path, yml_body: str) -> Template:
    return Template.load(_yml(tmp_path, yml_body))


def _run(src: Path, yml_body: str, tmp_path: Path):
    tmpl = _load(tmp_path, yml_body)
    return extract(src, tmpl)


# ======================================================================
# CSV-1  Basic CSV read via locate.source: csv
# ======================================================================


@pytest.mark.xfail(
    strict=True,
    reason="CSV-1: locate.source: csv not yet implemented; crease accepts xlsx only.",
)
def test_csv_basic_read_via_source_csv(tmp_path):
    csv_path = _csv(
        tmp_path,
        "customer,qty,amount\n" "Acme Co.,5,100\n" "Globex Corp,3,60\n" "Hooli Inc.,7,140\n",
    )
    result = _run(
        csv_path,
        """
        template_id: csv_basic
        version: 1
        entities:
          - name: order
            cardinality: many
            locate:
              source: csv
              orientation: flat
              header_row: 0
            fields:
              - { name: customer, source_column: "customer", type: string }
              - { name: qty, source_column: "qty", type: integer }
              - { name: amount, source_column: "amount", type: integer }
        """,
        tmp_path,
    )

    assert len(result.canonical["orders"]) == 3
    assert {r["customer"] for r in result.canonical["orders"]} == {
        "Acme Co.",
        "Globex Corp",
        "Hooli Inc.",
    }


# ======================================================================
# CSV-2  Numbers with thousand separators ("25,500" → 25500)
# ======================================================================


@pytest.mark.xfail(
    strict=True,
    reason="CSV-2: number_format: thousands not yet implemented; " "string '25,500' won't coerce to integer 25500.",
)
def test_csv_number_format_thousands_strips_commas(tmp_path):
    """``number_format: thousands`` on an integer/number field should strip
    `,` thousand separators before coercion. xlsx hands you 25500; CSV
    hands you ``"25,500"`` — same field, different format."""
    csv_path = _csv(
        tmp_path,
        "site,head_placed\n"
        'Site-A,"25,500"\n'
        'Site-B,"265,600"\n'
        "Site-C,1000\n",  # mixed: some rows have separators, some don't
    )
    result = _run(
        csv_path,
        """
        template_id: csv_thousands
        version: 1
        entities:
          - name: site
            cardinality: many
            locate:
              source: csv
              orientation: flat
              header_row: 0
            fields:
              - { name: site, source_column: "site", type: string }
              - { name: head_placed, source_column: "head_placed", type: integer, number_format: thousands }
        """,
        tmp_path,
    )

    assert [r["head_placed"] for r in result.canonical["sites"]] == [25500, 265600, 1000]


@pytest.mark.xfail(
    strict=True,
    reason="CSV-2b: default coercion is strict — a comma-separated number "
    "without number_format: thousands should fail loudly with a typed cause.",
)
def test_csv_thousands_separator_fails_loudly_without_opt_in(tmp_path):
    """If the operator forgets ``number_format: thousands``, the field
    should fail with ``wrong_type`` and ``ctx.likely_cause:
    csv_thousands_separator`` so they know exactly what to fix."""
    csv_path = _csv(tmp_path, 'site,head\nSite-A,"25,500"\n')
    tmpl = _load(
        tmp_path,
        """
        template_id: csv_thousands_strict
        version: 1
        entities:
          - name: site
            cardinality: many
            locate:
              source: csv
              orientation: flat
              header_row: 0
            fields:
              - { name: site, source_column: "site", type: string }
              - { name: head, source_column: "head", type: integer }
        """,
    )
    result = extract(csv_path, tmpl)
    report = validate(result, tmpl)
    matches = [e for e in report.errors() if e.type == "wrong_type" and e.loc[-1] == "head"]
    assert matches and matches[0].ctx.get("likely_cause") == "csv_thousands_separator"


# ======================================================================
# CSV-3  Percentages as strings ("73.3%" → 73.3 or 0.733)
# ======================================================================


@pytest.mark.xfail(
    strict=True,
    reason="CSV-3: number_format: percent not yet implemented; " "string '73.3%' won't coerce.",
)
def test_csv_number_format_percent_strips_percent_sign(tmp_path):
    """Two flavors: ``percent`` (string ``"73.3%"`` → 73.3 as a number, leave
    operator to divide if they want a 0-1 ratio) vs ``percent_fraction``
    (same string → 0.733). Test the basic ``percent`` form here.
    """
    csv_path = _csv(
        tmp_path,
        "site,saleable_pct\n" "Site-A,73.3%\n" "Site-B,81.0%\n" "Site-C,100%\n",
    )
    result = _run(
        csv_path,
        """
        template_id: csv_percent
        version: 1
        entities:
          - name: site
            cardinality: many
            locate:
              source: csv
              orientation: flat
              header_row: 0
            fields:
              - { name: site, source_column: "site", type: string }
              - { name: saleable_pct, source_column: "saleable_pct", type: number, number_format: percent }
        """,
        tmp_path,
    )

    assert [r["saleable_pct"] for r in result.canonical["sites"]] == [73.3, 81.0, 100.0]


# ======================================================================
# CSV-4  BOM in first header cell ("﻿Name" → matches "Name")
# ======================================================================


@pytest.mark.xfail(
    strict=True,
    reason="CSV-4: normalize_header doesn't strip UTF-8 BOM (\\ufeff); "
    "an Excel-exported CSV's first header silently fails source_column lookup.",
)
def test_csv_bom_in_first_header_is_stripped_during_normalization(tmp_path):
    """Excel's "Save As CSV UTF-8" emits a UTF-8 BOM at the start of the
    file. The first header cell becomes ``"\\ufeffSample Name"`` after the
    parser reads it. Header normalization should strip the BOM so
    ``source_column: "Sample Name"`` matches.
    """
    # ﻿ is the Unicode BOM character; encoded as UTF-8 it's 3 bytes.
    content_bytes = "﻿Sample Name,Bag Barcode\nS-001,B-1001\nS-002,B-1002\n".encode()
    csv_path = _csv(tmp_path, content_bytes)
    result = _run(
        csv_path,
        """
        template_id: csv_bom
        version: 1
        entities:
          - name: sample
            cardinality: many
            locate:
              source: csv
              orientation: flat
              header_row: 0
            fields:
              - { name: name, source_column: "Sample Name", type: string }
              - { name: bag, source_column: "Bag Barcode", type: string }
        """,
        tmp_path,
    )

    assert result.canonical["samples"][0] == {"name": "S-001", "bag": "B-1001"}


# ======================================================================
# CSV-5  Delimiter sniffing (semicolon, tab, pipe)
# ======================================================================


@pytest.mark.xfail(
    strict=True,
    reason="CSV-5: delimiter auto-detection (csv.Sniffer-equivalent) not yet "
    "implemented; locale-specific exports (European Excel uses ;) misread as one-column.",
)
def test_csv_auto_detects_semicolon_delimiter(tmp_path):
    """European-locale Excel exports CSV with ``;`` as the delimiter.
    With ``delimiter: auto`` the reader should sniff it correctly.
    """
    csv_path = _csv(
        tmp_path,
        "customer;qty;amount\n" "Acme Co.;5;100\n" "Globex Corp;3;60\n",
        name="semi.csv",
    )
    result = _run(
        csv_path,
        """
        template_id: csv_semicolon
        version: 1
        csv:
          delimiter: auto
        entities:
          - name: order
            cardinality: many
            locate:
              source: csv
              orientation: flat
              header_row: 0
            fields:
              - { name: customer, source_column: "customer", type: string }
              - { name: qty, source_column: "qty", type: integer }
              - { name: amount, source_column: "amount", type: integer }
        """,
        tmp_path,
    )

    assert len(result.canonical["orders"]) == 2
    assert result.canonical["orders"][0] == {"customer": "Acme Co.", "qty": 5, "amount": 100}


@pytest.mark.xfail(
    strict=True,
    reason="CSV-5b: explicit delimiter declaration not yet implemented.",
)
def test_csv_explicit_tab_delimiter(tmp_path):
    """Explicit ``delimiter: \"\\t\"`` for a TSV-style file."""
    csv_path = _csv(
        tmp_path,
        "customer\tqty\tamount\n" "Acme Co.\t5\t100\n",
        name="tabbed.csv",
    )
    result = _run(
        csv_path,
        """
        template_id: csv_tab
        version: 1
        csv:
          delimiter: "\\t"
        entities:
          - name: order
            cardinality: many
            locate:
              source: csv
              orientation: flat
              header_row: 0
            fields:
              - { name: customer, source_column: "customer", type: string }
              - { name: qty, source_column: "qty", type: integer }
              - { name: amount, source_column: "amount", type: integer }
        """,
        tmp_path,
    )

    assert result.canonical["orders"] == [{"customer": "Acme Co.", "qty": 5, "amount": 100}]


# ======================================================================
# CSV-6  Embedded newlines in quoted cells
# ======================================================================


@pytest.mark.xfail(
    strict=True,
    reason="CSV-6: quoted multi-line cell handling not yet implemented; " "naive line splitting would break.",
)
def test_csv_embedded_newlines_in_quoted_cells(tmp_path):
    """A free-text cell with an embedded newline (``"line1\\nline2"``) must
    parse as a single cell. Standard csv libs (python's csv, pandas) handle
    this when quoting is on. Crease's reader must too.
    """
    csv_path = _csv(
        tmp_path,
        "sample,comments\n" 'S-001,"line one\nline two"\n' 'S-002,"single line"\n',
    )
    result = _run(
        csv_path,
        """
        template_id: csv_embedded_newline
        version: 1
        entities:
          - name: sample
            cardinality: many
            locate:
              source: csv
              orientation: flat
              header_row: 0
            fields:
              - { name: sample, source_column: "sample", type: string }
              - { name: comments, source_column: "comments", type: string }
        """,
        tmp_path,
    )

    assert len(result.canonical["samples"]) == 2
    assert result.canonical["samples"][0]["comments"] == "line one\nline two"


# ======================================================================
# CSV-7  Encoding auto-detection (Windows-1252 fallback)
# ======================================================================


@pytest.mark.xfail(
    strict=True,
    reason="CSV-7: encoding auto-detection / fallback chain not yet implemented; "
    "non-UTF-8 files would error or mojibake silently.",
)
def test_csv_encoding_auto_falls_back_to_windows_1252(tmp_path):
    """Excel's plain "Save As CSV" on Windows emits Windows-1252 (a.k.a.
    cp1252) — not UTF-8. ``encoding: auto`` should try UTF-8 first and
    fall back to Windows-1252 when UTF-8 decode fails.
    """
    # A cell value with a Windows-1252-only character: 0x92 is the
    # "right single quotation mark" (curly apostrophe) in cp1252, not
    # valid UTF-8 by itself.
    raw = b"customer,note\nAcme Co.,it\x92s fine\nGlobex Corp,plain\n"
    csv_path = _csv(tmp_path, raw, name="windows.csv")
    result = _run(
        csv_path,
        """
        template_id: csv_encoding_auto
        version: 1
        csv:
          encoding: auto
        entities:
          - name: order
            cardinality: many
            locate:
              source: csv
              orientation: flat
              header_row: 0
            fields:
              - { name: customer, source_column: "customer", type: string }
              - { name: note, source_column: "note", type: string }
        """,
        tmp_path,
    )

    # After successful decode, the curly apostrophe should be U+2019.
    assert result.canonical["orders"][0]["note"] == "it’s fine"


@pytest.mark.xfail(
    strict=True,
    reason="CSV-7b: explicit encoding override (e.g. encoding: 'windows-1252') " "not yet implemented.",
)
def test_csv_explicit_encoding_windows_1252(tmp_path):
    raw = b"customer,note\nAcme Co.,it\x92s fine\n"
    csv_path = _csv(tmp_path, raw, name="forced.csv")
    result = _run(
        csv_path,
        """
        template_id: csv_encoding_explicit
        version: 1
        csv:
          encoding: windows-1252
        entities:
          - name: order
            cardinality: many
            locate:
              source: csv
              orientation: flat
              header_row: 0
            fields:
              - { name: customer, source_column: "customer", type: string }
              - { name: note, source_column: "note", type: string }
        """,
        tmp_path,
    )

    assert result.canonical["orders"][0]["note"] == "it’s fine"
