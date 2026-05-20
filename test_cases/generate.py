"""
Generate the Crease test corpus on disk.

For each case in ALL_CASES, write:
  test_cases/<name>/input.xlsx
  test_cases/<name>/template.yml
  test_cases/<name>/description.txt
  test_cases/<name>/expected.json
  test_cases/<name>/expected_issues.json
  test_cases/<name>/notes.md
"""
from pathlib import Path

from .cases import ALL_CASES


def generate(root: Path = None) -> dict:
    root = root or Path(__file__).parent
    summary = {"total": 0, "clean": 0, "corrupted": 0, "cases": []}
    for case_fn in ALL_CASES:
        case = case_fn()
        case.write(root)
        summary["total"] += 1
        if case.expected_issues:
            summary["corrupted"] += 1
        else:
            summary["clean"] += 1
        summary["cases"].append({
            "name": case.name,
            "verdict": case.expected_verdict,
            "n_issues": len(case.expected_issues),
        })
    return summary


def main():
    summary = generate()
    print(f"Generated {summary['total']} cases: "
          f"{summary['clean']} clean, {summary['corrupted']} corrupted")
    for c in summary["cases"]:
        print(f"  {c['name']:35} verdict={c['verdict']:14} issues={c['n_issues']}")


if __name__ == "__main__":
    main()
