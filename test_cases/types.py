"""TestCase dataclass and corpus helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import openpyxl
import yaml


@dataclass
class TestCase:
    """A single test fixture: input file + gold template + expected outputs."""

    name: str
    description: str  # what an operator would type to describe the cohort
    workbook: openpyxl.Workbook  # the input .xlsx
    template: dict  # gold-standard Crease template
    expected: dict  # expected output of extract(file, template)
    expected_verdict: str = "valid"  # valid | needs_review | reject
    expected_issues: list[dict] = field(default_factory=list)
    notes: str = ""  # human notes on what this case tests

    def write(self, root: Path) -> Path:
        target_dir = root / self.name
        target_dir.mkdir(parents=True, exist_ok=True)

        xlsx_path = target_dir / "input.xlsx"
        self.workbook.save(xlsx_path)

        # template.yml — gold-standard. The extractor uses this directly.
        (target_dir / "template.yml").write_text(
            yaml.safe_dump(self.template, sort_keys=False, default_flow_style=False, allow_unicode=True)
        )

        # description.txt — what an operator would describe; used to test LLM inference
        (target_dir / "description.txt").write_text(self.description.strip() + "\n")

        # expected.json — canonical JSON the extractor should produce
        (target_dir / "expected.json").write_text(json.dumps(self.expected, default=str, indent=2))

        # expected_issues.json — for corrupted cases
        (target_dir / "expected_issues.json").write_text(
            json.dumps(
                {
                    "verdict": self.expected_verdict,
                    "issues": self.expected_issues,
                },
                default=str,
                indent=2,
            )
        )

        # notes.md
        if self.notes:
            (target_dir / "notes.md").write_text(self.notes.strip() + "\n")

        return target_dir


def new_workbook() -> openpyxl.Workbook:
    """A fresh workbook with no default sheet."""
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    return wb


def write_rows(ws, rows: list[list[Any]]) -> None:
    for r in rows:
        ws.append(r)
