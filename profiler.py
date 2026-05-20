"""
A Profile is the "model" — what a valid file is expected to look like.

For v1 we derive profiles directly from the Series/CrosstabSeries
definitions in series.py. In a real system the profiler would learn
profiles from known-good customer files; that's a later step.
"""
from dataclasses import dataclass, asdict
from typing import Any
import datetime as dt
import json
import re
from pathlib import Path

from series import SERIES, CROSSTABS, Series, CrosstabSeries


DTYPE_INT = "int"
DTYPE_FLOAT = "float"
DTYPE_STR = "str"
DTYPE_DATE = "date"
DTYPE_EMAIL = "email"
DTYPE_UUID = "uuid"


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def infer_dtype(value: Any) -> str:
    if isinstance(value, bool):
        return DTYPE_INT
    if isinstance(value, int):
        return DTYPE_INT
    if isinstance(value, float):
        return DTYPE_FLOAT
    if isinstance(value, (dt.date, dt.datetime)):
        return DTYPE_DATE
    if isinstance(value, str):
        if _DATE_RE.match(value):
            return DTYPE_DATE
        if _EMAIL_RE.match(value):
            return DTYPE_EMAIL
        if _UUID_RE.match(value):
            return DTYPE_UUID
        return DTYPE_STR
    return DTYPE_STR


def value_matches(value: Any, dtype: str) -> bool:
    """Is `value` consistent with the expected dtype? None handled separately."""
    if value is None:
        return False  # caller decides nullability
    if dtype == DTYPE_INT:
        # accept int-valued floats too (Excel often loads ints as floats)
        if isinstance(value, bool):
            return True
        if isinstance(value, int):
            return True
        if isinstance(value, float) and value.is_integer():
            return True
        return False
    if dtype == DTYPE_FLOAT:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if dtype == DTYPE_DATE:
        if isinstance(value, (dt.date, dt.datetime)):
            return True
        return isinstance(value, str) and bool(_DATE_RE.match(value))
    if dtype == DTYPE_EMAIL:
        return isinstance(value, str) and bool(_EMAIL_RE.match(value))
    if dtype == DTYPE_UUID:
        return isinstance(value, str) and bool(_UUID_RE.match(value))
    if dtype == DTYPE_STR:
        return isinstance(value, str)
    return False


@dataclass
class Profile:
    name: str           # e.g. "orders_flat"
    source: str         # series or crosstab name
    layout: str         # flat | transposed | property_sheet | crosstab
    expected_labels: list[str]   # column names / labels / col-dim headers
    expected_dtypes: dict[str, str]
    nullable: dict[str, bool]
    min_data_rows: int = 1


def _profile_from_series(series: Series, layout: str) -> Profile:
    # sample multiple records so dtype inference isn't fooled by a single
    # record that happens to have e.g. an int for a float column.
    samples = series.make_records(20)
    dtypes: dict[str, str] = {}
    for col in series.columns:
        # take the most common inferred dtype across samples
        observed = [infer_dtype(s[col]) for s in samples]
        dtypes[col] = max(set(observed), key=observed.count)
    return Profile(
        name=f"{series.name}_{layout}",
        source=series.name,
        layout=layout,
        expected_labels=list(series.columns),
        expected_dtypes=dtypes,
        nullable={c: False for c in series.columns},
        min_data_rows=1 if layout in ("transposed", "property_sheet") else 5,
    )


def _profile_from_crosstab(spec: CrosstabSeries) -> Profile:
    sample_value = spec.value_factory()
    value_dtype = infer_dtype(sample_value)
    return Profile(
        name=f"{spec.name}_crosstab",
        source=spec.name,
        layout="crosstab",
        expected_labels=list(spec.col_labels),
        expected_dtypes={c: value_dtype for c in spec.col_labels},
        nullable={c: False for c in spec.col_labels},
        min_data_rows=2,
    )


def build_profiles() -> dict[str, Profile]:
    """Build every profile we know about, keyed by (source, layout)."""
    profiles: dict[str, Profile] = {}
    for series_name, series in SERIES.items():
        for layout in ("flat", "transposed", "property_sheet"):
            p = _profile_from_series(series, layout)
            profiles[f"{series_name}__{layout}"] = p
    for crosstab_name, spec in CROSSTABS.items():
        p = _profile_from_crosstab(spec)
        profiles[f"{crosstab_name}__crosstab"] = p
    return profiles


def save_profiles(profiles: dict[str, Profile], path: Path) -> None:
    path.write_text(json.dumps(
        {k: asdict(v) for k, v in profiles.items()}, indent=2
    ))


def load_profiles(path: Path) -> dict[str, Profile]:
    raw = json.loads(path.read_text())
    return {k: Profile(**v) for k, v in raw.items()}


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, default=Path("artifacts/profiles.json"))
    args = p.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    profiles = build_profiles()
    save_profiles(profiles, args.out)
    print(f"wrote {len(profiles)} profiles to {args.out}")
    for k, prof in profiles.items():
        print(f"  {k}: {len(prof.expected_labels)} labels, layout={prof.layout}")


if __name__ == "__main__":
    main()
