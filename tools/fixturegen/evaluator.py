"""
Run the scorer over a labeled eval set, compute metrics.

For each file:
  - load the label.json (ground truth)
  - pick the matching profile from (source, layout)
  - run the scorer
  - compare predicted verdict vs actual verdict
  - compare predicted reasons vs actual reason

Output a metrics.json with:
  - file-level confusion matrix (actual × predicted verdicts)
  - per-reason recall (when actual reason = X, how often did we detect it?)
  - precision/recall summary
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path

from profiler import build_profiles
from scorer import score_file

VERDICTS = ["valid", "needs_review", "reject"]


def evaluate(eval_dir: Path) -> dict:
    profiles = build_profiles()
    records = []

    label_files = sorted(eval_dir.rglob("*.label.json"))
    for label_path in label_files:
        label = json.loads(label_path.read_text())
        xlsx_path = label_path.with_suffix("").with_suffix(".xlsx")
        if not xlsx_path.exists():
            continue

        key = f"{label['source']}__{label['layout']}"
        profile = profiles.get(key)
        if profile is None:
            continue

        verdict = score_file(xlsx_path, profile)
        predicted_reasons = set(verdict.reasons())
        actual_reason = label.get("reason")

        records.append(
            {
                "file": str(xlsx_path.relative_to(eval_dir)),
                "actual_verdict": label["verdict"],
                "predicted_verdict": verdict.verdict,
                "actual_reason": actual_reason,
                "predicted_reasons": sorted(predicted_reasons),
                "verdict_correct": label["verdict"] == verdict.verdict,
                "reason_detected": (actual_reason in predicted_reasons if actual_reason else True),
            }
        )

    # confusion matrix
    confusion = {a: {p: 0 for p in VERDICTS} for a in VERDICTS}
    for r in records:
        if r["actual_verdict"] in VERDICTS and r["predicted_verdict"] in VERDICTS:
            confusion[r["actual_verdict"]][r["predicted_verdict"]] += 1

    # per-reason recall
    by_reason = defaultdict(lambda: {"total": 0, "detected": 0})
    for r in records:
        ar = r["actual_reason"] or "_clean"
        by_reason[ar]["total"] += 1
        if r["reason_detected"]:
            by_reason[ar]["detected"] += 1

    reason_recall = {
        reason: {
            "total": v["total"],
            "detected": v["detected"],
            "recall": round(v["detected"] / v["total"], 3) if v["total"] else 0.0,
        }
        for reason, v in sorted(by_reason.items())
    }

    correct = sum(1 for r in records if r["verdict_correct"])
    total = len(records)
    metrics = {
        "total_files": total,
        "verdict_accuracy": round(correct / total, 3) if total else 0.0,
        "confusion_matrix": confusion,
        "reason_recall": reason_recall,
    }
    return {"metrics": metrics, "records": records}


def print_metrics(metrics: dict) -> None:
    m = metrics["metrics"]
    print(f"\nTotal files:     {m['total_files']}")
    print(f"Verdict accuracy: {m['verdict_accuracy']:.1%}")
    print("\nConfusion matrix (rows = actual, cols = predicted):")
    print(f"  {'':<14} {'valid':>14} {'needs_review':>14} {'reject':>14}")
    for actual in VERDICTS:
        row = m["confusion_matrix"][actual]
        print(f"  {actual:<14} {row['valid']:>14} {row['needs_review']:>14} {row['reject']:>14}")
    print("\nReason recall:")
    print(f"  {'reason':<22} {'total':>6} {'detected':>10} {'recall':>8}")
    for reason, v in m["reason_recall"].items():
        print(f"  {reason:<22} {v['total']:>6} {v['detected']:>10} {v['recall']:>8.1%}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--eval-dir", type=Path, default=Path("data/eval_smoke"))
    p.add_argument("--out", type=Path, default=Path("artifacts/metrics.json"))
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args()

    result = evaluate(args.eval_dir)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2))

    if not args.quiet:
        print_metrics(result)
    print(f"\nWrote metrics to {args.out}")


if __name__ == "__main__":
    main()
