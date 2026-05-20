"""Run every fixture in test_cases/ through extract + validate; compare to expected."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from crease import Template, extract, validate

CORPUS_ROOT = Path(__file__).parent.parent / "test_cases"


def _case_dirs() -> list[Path]:
    return sorted(
        p
        for p in CORPUS_ROOT.iterdir()
        if p.is_dir() and (p / "input.xlsx").exists() and (p / "template.yml").exists()
    )


@pytest.mark.parametrize("case_dir", _case_dirs(), ids=lambda p: p.name)
def test_extraction(case_dir: Path) -> None:
    template = Template.load(case_dir / "template.yml")
    result = extract(case_dir / "input.xlsx", template)
    expected = json.loads((case_dir / "expected.json").read_text())

    # Compare per-entity payloads (drop envelope keys that may vary).
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
    template = Template.load(case_dir / "template.yml")
    result = extract(case_dir / "input.xlsx", template)
    report = validate(result, template)
    expected = json.loads((case_dir / "expected_issues.json").read_text())

    assert report.verdict == expected["verdict"], (
        f"{case_dir.name}: verdict {report.verdict!r} != expected {expected['verdict']!r}\n"
        f"  issues seen: {[i.to_dict() for i in report.issues[:5]]}"
    )

    # Loose check: every expected issue should appear in actual issues (matched by
    # (entity, field, reason) — row may shift by ±1 across implementations).
    actual_keys = {(i.entity, i.field, i.reason) for i in report.issues}
    for exp_issue in expected.get("issues", []):
        key = (exp_issue.get("entity"), exp_issue.get("field"), exp_issue.get("reason"))
        assert key in actual_keys, (
            f"{case_dir.name}: expected issue {exp_issue} not found.\n"
            f"  actual: {sorted(actual_keys)}"
        )
