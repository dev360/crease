"""Tests for the multi-backend read layer.

Covers:
- Backend auto-selection (calamine by default; openpyxl when the template
  declares ``locate.skip_hidden_rows: true``).
- Explicit ``engine=`` override on the public API.
- End-to-end read of a legacy ``.xls`` (BIFF) file via calamine, which
  openpyxl cannot read at all.
- ``skip_hidden_rows`` correctly drops hidden rows on the openpyxl path
  and (by design) keeps them on the calamine path.
"""

from __future__ import annotations

from pathlib import Path

import openpyxl
import pytest

import crease
from crease import Template, extract
from crease._workbook import open_workbook, select_engine
from crease.template_model import Entity, Locate, Template as TemplateModel


CORPUS_ROOT = Path(__file__).parent.parent / "test_cases"


# ---- select_engine ------------------------------------------------------


def _template_without_hidden_rows() -> TemplateModel:
    return TemplateModel(
        template_id="t",
        description="d",
        entities=[
            Entity(
                name="x",
                cardinality="many",
                locate=Locate(tab="Sheet1", orientation="flat"),
                fields=[],
            )
        ],
    )


def _template_with_hidden_rows() -> TemplateModel:
    return TemplateModel(
        template_id="t",
        description="d",
        entities=[
            Entity(
                name="x",
                cardinality="many",
                locate=Locate(tab="Sheet1", orientation="flat", skip_hidden_rows=True),
                fields=[],
            )
        ],
    )


def test_select_engine_defaults_to_calamine() -> None:
    assert select_engine(_template_without_hidden_rows(), None) == "calamine"


def test_select_engine_routes_skip_hidden_rows_to_openpyxl() -> None:
    assert select_engine(_template_with_hidden_rows(), None) == "openpyxl"


def test_select_engine_explicit_override_wins_over_skip_hidden_rows() -> None:
    # Sanity check that the override is honored — the user owns the trade-off
    # (they lose hidden-row detection but get calamine's broader format support).
    assert select_engine(_template_with_hidden_rows(), "calamine") == "calamine"


def test_select_engine_explicit_override_wins_over_default() -> None:
    assert select_engine(_template_without_hidden_rows(), "openpyxl") == "openpyxl"


def test_select_engine_rejects_unknown_value() -> None:
    with pytest.raises(ValueError, match="must be 'calamine' or 'openpyxl'"):
        select_engine(None, "unknown-backend")


# ---- engine= kwarg on the public API ------------------------------------


def test_extract_records_chosen_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    """Spy on `open_workbook` to confirm the kwarg reaches the dispatcher."""
    seen: list[str] = []
    real = open_workbook

    def spy(path: Path, engine: str):
        seen.append(engine)
        return real(path, engine)

    monkeypatch.setattr("crease.extractor.open_workbook", spy)

    case_dir = CORPUS_ROOT / "flat_simple"
    template = Template.load(case_dir / "template.yml")

    extract(case_dir / "input.xlsx", template)
    assert seen[-1] == "calamine"

    extract(case_dir / "input.xlsx", template, engine="openpyxl")
    assert seen[-1] == "openpyxl"

    extract(case_dir / "input.xlsx", template, engine="calamine")
    assert seen[-1] == "calamine"


# ---- .xls end-to-end ----------------------------------------------------


def test_reads_legacy_xls_via_calamine() -> None:
    """openpyxl cannot read .xls at all; calamine handles BIFF natively."""
    case_dir = CORPUS_ROOT / "legacy_xls"
    template = Template.load(case_dir / "template.yml")
    result = extract(case_dir / "input.xls", template)

    assert result.report.is_valid, [e.to_dict() for e in result.report.errors()]
    orders = result.canonical["orders"]
    assert len(orders) == 5
    assert orders[0]["order_id"] == "ORD-1000"
    assert orders[0]["quantity"] == 82
    assert orders[0]["unit_price"] == 120.22


# ---- skip_hidden_rows path ---------------------------------------------


def _build_workbook_with_hidden_row(path: Path) -> None:
    """Build a tiny order table where row 4 (1-indexed) is hidden in Excel."""
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("Orders")
    ws.append(["order_id", "quantity"])
    ws.append(["ORD-1001", 10])
    ws.append(["ORD-1002", 20])
    ws.append(["ORD-1003", 30])  # row index 4 — to be hidden
    ws.append(["ORD-1004", 40])
    ws.row_dimensions[4].hidden = True
    wb.save(path)


def _hidden_row_template(skip: bool) -> TemplateModel:
    return TemplateModel(
        template_id="hidden_row_demo",
        description="hidden row demo",
        entities=[
            Entity(
                name="order",
                cardinality="many",
                locate=Locate(
                    tab="Orders",
                    orientation="flat",
                    header_row=0,
                    skip_hidden_rows=skip,
                ),
                fields=[
                    crease.FieldSpec(name="order_id", source_column="order_id", type="string"),
                    crease.FieldSpec(name="quantity", source_column="quantity", type="integer"),
                ],
            )
        ],
    )


def test_skip_hidden_rows_picks_openpyxl_and_drops_hidden(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []
    real = open_workbook

    def spy(path: Path, engine: str):
        seen.append(engine)
        return real(path, engine)

    monkeypatch.setattr("crease.extractor.open_workbook", spy)

    xlsx = tmp_path / "hidden.xlsx"
    _build_workbook_with_hidden_row(xlsx)

    template = _hidden_row_template(skip=True)
    result = extract(xlsx, template)

    assert seen == ["openpyxl"], "skip_hidden_rows must auto-dispatch to openpyxl"

    order_ids = [r["order_id"] for r in result.canonical["orders"]]
    assert "ORD-1003" not in order_ids, "the hidden row should be dropped"
    assert order_ids == ["ORD-1001", "ORD-1002", "ORD-1004"]


def test_calamine_cannot_see_hidden_rows(tmp_path: Path) -> None:
    """If the user overrides to calamine, hidden-row detection silently degrades.

    This is documented behavior: calamine doesn't expose row-hidden state,
    so `skip_hidden_rows` becomes a no-op on that backend. We assert the
    degraded behavior so anyone who changes the adapter notices.
    """
    xlsx = tmp_path / "hidden.xlsx"
    _build_workbook_with_hidden_row(xlsx)

    template = _hidden_row_template(skip=True)
    result = extract(xlsx, template, engine="calamine")

    order_ids = [r["order_id"] for r in result.canonical["orders"]]
    assert "ORD-1003" in order_ids


# ---- session + check carry the kwarg through ----------------------------


def test_session_open_honors_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    real = open_workbook

    def spy(path: Path, engine: str):
        seen.append(engine)
        return real(path, engine)

    monkeypatch.setattr("crease.extractor.open_workbook", spy)

    case_dir = CORPUS_ROOT / "flat_simple"
    template = Template.load(case_dir / "template.yml")
    with crease.open(case_dir / "input.xlsx", template, engine="openpyxl"):
        pass
    assert seen == ["openpyxl"]


def test_check_honors_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    real = open_workbook

    def spy(path: Path, engine: str):
        seen.append(engine)
        return real(path, engine)

    monkeypatch.setattr("crease.extractor.open_workbook", spy)

    case_dir = CORPUS_ROOT / "flat_simple"
    template = Template.load(case_dir / "template.yml")
    crease.check(case_dir / "input.xlsx", template, engine="openpyxl")
    assert seen == ["openpyxl"]
