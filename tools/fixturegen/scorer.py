"""
Scorer: given an xlsx file + a Profile, produce a verdict + issues.

Layout-aware. The verdict aggregates issues:
  - any structural issue (missing/renamed/swapped columns) → "reject"
  - any row/cell issue → "needs_review"
  - no issues → "valid"
"""
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any
import json

import openpyxl

from profiler import Profile, value_matches
from sheet import Sheet


@dataclass
class Issue:
    reason: str
    severity: str             # "structural" (→ reject) or "data" (→ needs_review)
    row: int | None = None
    col: int | None = None
    label: str | None = None
    details: dict = field(default_factory=dict)


@dataclass
class Verdict:
    verdict: str              # valid | needs_review | reject
    issues: list[Issue] = field(default_factory=list)

    def reasons(self) -> list[str]:
        return sorted({i.reason for i in self.issues})


def read_sheet(path: Path) -> Sheet:
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.active
    sheet: Sheet = []
    for row in ws.iter_rows(values_only=True):
        sheet.append(list(row))
    # strip fully-empty trailing rows (openpyxl can pad these)
    while sheet and all(v is None for v in sheet[-1]):
        sheet.pop()
    return sheet


# ---------- layout-specific extraction ----------

def _extract_flat(sheet: Sheet, profile: Profile) -> tuple[list[str], list[list[Any]]]:
    headers = [str(h) if h is not None else "" for h in sheet[0]]
    data = sheet[1:]
    return headers, data


def _extract_transposed(sheet: Sheet, profile: Profile) -> tuple[list[str], list[list[Any]]]:
    headers = [str(h) if h is not None else "" for h in sheet[0]]
    data = sheet[1:2]  # exactly one value row
    return headers, data


def _extract_property_sheet(sheet: Sheet, profile: Profile) -> tuple[list[str], list[list[Any]]]:
    # column 0 holds labels, column 1 holds values
    labels = [str(r[0]) if r and r[0] is not None else "" for r in sheet]
    values = [[r[1] if len(r) > 1 else None] for r in sheet]
    # caller will check labels match profile.expected_labels in order
    return labels, values


def _extract_crosstab(sheet: Sheet, profile: Profile) -> tuple[list[str], list[list[Any]]]:
    # row 0: [corner, col_label_1, col_label_2, ...]
    # rows 1..N: [row_label, value, value, ...]
    headers = [str(h) if h is not None else "" for h in sheet[0][1:]]
    data = [r[1:] for r in sheet[1:]]
    return headers, data


EXTRACTORS = {
    "flat": _extract_flat,
    "transposed": _extract_transposed,
    "property_sheet": _extract_property_sheet,
    "crosstab": _extract_crosstab,
}


# ---------- core scoring ----------

def score_sheet(sheet: Sheet, profile: Profile) -> Verdict:
    issues: list[Issue] = []
    extractor = EXTRACTORS[profile.layout]
    headers, data = extractor(sheet, profile)

    # 1. Structural: do headers/labels match what we expect?
    expected = profile.expected_labels
    if len(headers) != len(expected):
        issues.append(Issue(
            reason="column_count_mismatch",
            severity="structural",
            details={"expected": len(expected), "got": len(headers)},
        ))
    else:
        for i, (got, want) in enumerate(zip(headers, expected)):
            if got != want:
                issues.append(Issue(
                    reason="header_renamed",
                    severity="structural",
                    col=i,
                    label=want,
                    details={"expected": want, "got": got},
                ))

    # If structural issues already make per-cell checks meaningless,
    # short-circuit. (We still try the cell checks below — they're useful
    # for transposed/property where label drift can still allow row-wise
    # validation by position.)
    if not issues:
        # 2. Row count sanity
        if len(data) < profile.min_data_rows:
            issues.append(Issue(
                reason="too_few_rows",
                severity="structural",
                details={"expected_min": profile.min_data_rows, "got": len(data)},
            ))

    # 3. Per-cell: nullability + dtype
    for r_idx, row in enumerate(data):
        is_blank_row = all(v is None for v in row)
        if is_blank_row:
            issues.append(Issue(
                reason="empty_row",
                severity="data",
                row=r_idx,
            ))
            continue
        for c_idx, value in enumerate(row):
            if c_idx >= len(expected):
                continue
            label = expected[c_idx]
            dtype = profile.expected_dtypes.get(label)
            if dtype is None:
                continue
            if value is None:
                if not profile.nullable.get(label, False):
                    issues.append(Issue(
                        reason="missing_value",
                        severity="data",
                        row=r_idx, col=c_idx, label=label,
                    ))
                continue
            if not value_matches(value, dtype):
                issues.append(Issue(
                    reason="wrong_dtype",
                    severity="data",
                    row=r_idx, col=c_idx, label=label,
                    details={"expected": dtype, "got": repr(value)[:40]},
                ))

    # 4. Duplicate-row detection (data rows only)
    seen: dict[tuple, int] = {}
    for r_idx, row in enumerate(data):
        key = tuple(row)
        if key in seen and not all(v is None for v in row):
            issues.append(Issue(
                reason="duplicate_row",
                severity="data",
                row=r_idx,
                details={"duplicate_of": seen[key]},
            ))
        else:
            seen[key] = r_idx

    # 5. Aggregate verdict
    if any(i.severity == "structural" for i in issues):
        verdict = "reject"
    elif issues:
        verdict = "needs_review"
    else:
        verdict = "valid"

    return Verdict(verdict=verdict, issues=issues)


def score_file(xlsx_path: Path, profile: Profile) -> Verdict:
    sheet = read_sheet(xlsx_path)
    return score_sheet(sheet, profile)


def verdict_to_dict(v: Verdict) -> dict:
    return {
        "verdict": v.verdict,
        "reasons": v.reasons(),
        "issues": [asdict(i) for i in v.issues],
    }


def main():
    import argparse
    from profiler import load_profiles

    p = argparse.ArgumentParser()
    p.add_argument("xlsx", type=Path)
    p.add_argument("--profile-key", required=True,
                   help="e.g. orders__flat or sales_by_region_quarter__crosstab")
    p.add_argument("--profiles", type=Path, default=Path("artifacts/profiles.json"))
    args = p.parse_args()

    profiles = load_profiles(args.profiles)
    profile = profiles[args.profile_key]
    verdict = score_file(args.xlsx, profile)
    print(json.dumps(verdict_to_dict(verdict), indent=2))


if __name__ == "__main__":
    main()
