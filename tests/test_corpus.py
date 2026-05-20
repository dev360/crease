"""Run every fixture in test_cases/ through extract + validate.

The corpus is the authoritative spec — each labeled fixture asserts both the
canonical JSON output and the expected error set (matched loosely by
(entity, field, type) tuple, since row indexes can shift across
implementations).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from crease import Template, extract, validate

CORPUS_ROOT = Path(__file__).parent.parent / "test_cases"


def _case_dirs() -> list[Path]:
    return sorted(
        p for p in CORPUS_ROOT.iterdir() if p.is_dir() and (p / "input.xlsx").exists() and (p / "template.yml").exists()
    )


@pytest.mark.parametrize("case_dir", _case_dirs(), ids=lambda p: p.name)
def test_extraction(case_dir: Path) -> None:
    """Canonical payload matches the labeled expected.json."""
    template = Template.load(case_dir / "template.yml")
    result = extract(case_dir / "input.xlsx", template)
    expected = json.loads((case_dir / "expected.json").read_text())

    for key, exp_value in expected.items():
        if key in ("template_id", "source_file", "errors"):
            continue
        got = result.canonical.get(key)
        assert got == exp_value, (
            f"{case_dir.name}: entity {key!r} differs.\n"
            f"  expected: {json.dumps(exp_value, default=str, indent=2)[:500]}\n"
            f"  got:      {json.dumps(got, default=str, indent=2)[:500]}"
        )


@pytest.mark.parametrize("case_dir", _case_dirs(), ids=lambda p: p.name)
def test_validation(case_dir: Path) -> None:
    """Report's is_valid + error set match the labeled expected_issues.json.

    The corpus's expected_issues.json still uses the legacy `verdict` /
    `issues` keys. The test translates: ``verdict == "valid"`` → expect
    ``report.is_valid``; non-valid verdicts → expect at least the listed
    errors (matched by (entity, field, type) — rows can shift ±1).
    """
    template = Template.load(case_dir / "template.yml")
    result = extract(case_dir / "input.xlsx", template)
    report = validate(result, template)
    expected = json.loads((case_dir / "expected_issues.json").read_text())

    expected_valid = expected.get("verdict") == "valid"
    assert report.is_valid == expected_valid, (
        f"{case_dir.name}: is_valid={report.is_valid} but expected verdict "
        f"{expected.get('verdict')!r}.\n"
        f"  errors seen: {[e.to_dict() for e in report.errors()[:5]]}"
    )

    expected_reject = expected.get("verdict") == "reject"
    if expected_reject:
        assert report.has_structural, (
            f"{case_dir.name}: expected structural errors (verdict=reject) "
            f"but none found. Errors: {[e.type for e in report.errors()]}"
        )

    actual_keys = {(e.loc[0], e.loc[2], e.type) for e in report.errors()}
    for exp_issue in expected.get("issues", []):
        key = (exp_issue.get("entity"), exp_issue.get("field"), exp_issue.get("reason"))
        assert key in actual_keys, (
            f"{case_dir.name}: expected issue {exp_issue} not found.\n"
            f"  actual: {sorted(str(k) for k in actual_keys)}"
        )


@pytest.mark.parametrize("case_dir", _case_dirs(), ids=lambda p: p.name)
def test_result_has_template_reference(case_dir: Path) -> None:
    """The ExtractResult carries the template, enabling .report and projection."""
    template = Template.load(case_dir / "template.yml")
    result = extract(case_dir / "input.xlsx", template)

    assert result.template is template
    # .report is a property; calling it should produce a Report.
    report = result.report
    assert report is result.report, "report should be cached after first access"
