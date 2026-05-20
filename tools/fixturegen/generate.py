"""
Generate a labeled eval set.

A scenario = (data source, layout, optional corruption). Data source is
either a Series (flat records) rendered into one of three layouts, or
a CrosstabSeries (always rendered as a crosstab).

Each scenario writes:
  data/<set>/<source>/<layout>/<id>.xlsx
  data/<set>/<source>/<layout>/<id>.label.json
"""
import argparse
import json
import random
from pathlib import Path

import corruptors
from layouts import (
    LAYOUTS, render_flat, render_transposed, render_property_sheet,
    render_crosstab,
)
from series import SERIES, CROSSTABS
from sheet import write_xlsx


CLEAN_RATIO = 0.3


SERIES_LAYOUT_RENDERERS = {
    "flat": render_flat,
    "transposed": render_transposed,
    "property_sheet": render_property_sheet,
}


def _render_series(series_name: str, layout_name: str,
                   n_records: int, rng: random.Random):
    series = SERIES[series_name]
    renderer = SERIES_LAYOUT_RENDERERS[layout_name]
    return renderer(series, n_records, rng)


def _render_crosstab(crosstab_name: str, rng: random.Random):
    spec = CROSSTABS[crosstab_name]
    return render_crosstab(spec, rng)


def _save(sheet, label: dict, scenario_id: str, source: str, layout_name: str,
          out_dir: Path):
    target_dir = out_dir / source / layout_name
    target_dir.mkdir(parents=True, exist_ok=True)
    xlsx_path = target_dir / f"{scenario_id}.xlsx"
    label_path = target_dir / f"{scenario_id}.label.json"
    write_xlsx(sheet, xlsx_path)
    full_label = {
        "scenario_id": scenario_id,
        "source": source,
        "layout": layout_name,
        **label,
    }
    label_path.write_text(json.dumps(full_label, indent=2))
    return full_label


def _maybe_corrupt(sheet, layout_name: str, rng: random.Random):
    if rng.random() < CLEAN_RATIO:
        return corruptors.CorruptionResult(sheet, {
            "verdict": "valid",
            "bad_rows": [],
            "bad_cells": [],
            "reason": None,
        })
    layout = LAYOUTS[layout_name]
    kind = rng.choice(layout.applicable_corruptions)
    return corruptors.apply(kind, sheet, layout, rng)


def generate(out_dir: Path, per_combo: int, rows_per_file: int, seed: int):
    rng = random.Random(seed)
    out_dir.mkdir(parents=True, exist_ok=True)

    summary = {"total": 0, "by_source": {}, "by_layout": {},
               "by_reason": {}, "by_verdict": {}}

    combos: list[tuple[str, str, str]] = []  # (source_type, source_name, layout)
    for series_name in SERIES:
        for layout_name in SERIES_LAYOUT_RENDERERS:
            combos.append(("series", series_name, layout_name))
    for crosstab_name in CROSSTABS:
        combos.append(("crosstab", crosstab_name, "crosstab"))

    counter = 0
    for source_type, source_name, layout_name in combos:
        for i in range(per_combo):
            # per-scenario RNG seeding for reproducibility of corruption picks
            scenario_rng = random.Random((seed, source_name, layout_name, i).__hash__())

            if source_type == "series":
                sheet = _render_series(source_name, layout_name,
                                       rows_per_file, scenario_rng)
            else:
                sheet = _render_crosstab(source_name, scenario_rng)

            result = _maybe_corrupt(sheet, layout_name, rng)
            scenario_id = f"{source_name}_{layout_name}_{i:04d}"
            label = _save(result.sheet, result.label, scenario_id,
                          source_name, layout_name, out_dir)

            counter += 1
            summary["total"] += 1
            summary["by_source"][source_name] = (
                summary["by_source"].get(source_name, 0) + 1
            )
            summary["by_layout"][layout_name] = (
                summary["by_layout"].get(layout_name, 0) + 1
            )
            reason_key = label["reason"] or "_clean"
            summary["by_reason"][reason_key] = (
                summary["by_reason"].get(reason_key, 0) + 1
            )
            summary["by_verdict"][label["verdict"]] = (
                summary["by_verdict"].get(label["verdict"], 0) + 1
            )

    (out_dir / "_summary.json").write_text(json.dumps(summary, indent=2))
    return summary


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, default=Path("data/eval"))
    p.add_argument("--per-combo", type=int, default=20,
                   help="files per (source × layout) combination")
    p.add_argument("--rows-per-file", type=int, default=50,
                   help="data rows for flat layout; ignored by transposed/property/crosstab")
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    summary = generate(args.out, args.per_combo, args.rows_per_file, args.seed)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
