"""Crease CLI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from crease.extractor import extract, stream
from crease.template_model import Template
from crease.validator import check

_BATCH_SUFFIXES = (".xlsx", ".xlsm", ".xls", ".xlsb", ".ods")


def _load_template(path: str) -> Template:
    return Template.load(Path(path))


def _cmd_extract(args: argparse.Namespace) -> int:
    template = _load_template(args.template)
    result = extract(args.file, template, engine=args.engine)
    out = json.dumps(result.canonical, default=str, indent=None if args.compact else 2)
    if args.out:
        Path(args.out).write_text(out)
    else:
        sys.stdout.write(out)
        sys.stdout.write("\n")
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    template = _load_template(args.template)
    _, report = check(args.file, template, engine=args.engine)
    if args.json:
        sys.stdout.write(json.dumps(report.to_dict(), default=str, indent=2))
        sys.stdout.write("\n")
    else:
        status = "valid" if report.is_valid else ("reject" if report.has_structural else "needs_review")
        sys.stderr.write(f"status: {status}\n")
        sys.stderr.write(f"errors: {report.error_count()}\n")
        for e in report.errors()[:50]:
            loc = ".".join(str(p) for p in e.loc if p is not None)
            sys.stderr.write(f"  - {e.type} at {loc or '<no-loc>'}: {e.msg}\n")

    return _exit_code(report, args.fail_on)


def _exit_code(report, fail_on: str) -> int:
    """CLI exit code policy:

    0 if the report is at or below the configured failure threshold.
    1 for cell-level errors when ``--fail-on=cell``.
    2 for structural errors when ``--fail-on`` is ``structural`` or ``cell``.
    """
    if report.is_valid:
        return 0
    if report.has_structural:
        return 2 if fail_on in ("structural", "cell") else 0
    return 1 if fail_on == "cell" else 0


def _cmd_check(args: argparse.Namespace) -> int:
    template = _load_template(args.template)
    result, report = check(args.file, template, engine=args.engine)
    payload = {**result.canonical, "_report": report.to_dict()}
    sys.stdout.write(json.dumps(payload, default=str, indent=None if args.compact else 2))
    sys.stdout.write("\n")
    return 0


def _cmd_stream(args: argparse.Namespace) -> int:
    template = _load_template(args.template)
    for record in stream(
        args.file,
        template,
        entity=args.entity,
        allow_partial=args.allow_partial,
        engine=args.engine,
    ):
        sys.stdout.write(json.dumps(record, default=str))
        sys.stdout.write("\n")
    return 0


def _iter_batch_inputs(root: Path) -> list[Path]:
    seen: set[Path] = set()
    for suffix in _BATCH_SUFFIXES:
        for path in root.glob(f"*{suffix}"):
            seen.add(path)
    return sorted(seen)


def _cmd_batch(args: argparse.Namespace) -> int:
    template = _load_template(args.template)
    out_dir = Path(args.out) if args.out else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    for path in _iter_batch_inputs(Path(args.dir)):
        result, report = check(path, template, engine=args.engine)
        if out_dir:
            (out_dir / f"{path.stem}.json").write_text(json.dumps(result.canonical, default=str, indent=2))
        status = "valid" if report.is_valid else ("reject" if report.has_structural else "needs_review")
        rows.append(
            {
                "file": path.name,
                "status": status,
                "error_count": report.error_count(),
            }
        )
        sys.stderr.write(f"  {path.name}: {status} ({report.error_count()} errors)\n")
    if args.report:
        Path(args.report).write_text(json.dumps(rows, indent=2))
    return 0


def _add_engine_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--engine",
        choices=["calamine", "openpyxl"],
        default=None,
        help="force a read backend (default: auto-select)",
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="crease", description="Declarative Excel-to-JSON extraction.")
    subs = p.add_subparsers(dest="cmd", required=True)

    e = subs.add_parser("extract", help="Extract canonical JSON from a file.")
    e.add_argument("file")
    e.add_argument("--template", required=True)
    e.add_argument("-o", "--out")
    e.add_argument("--compact", action="store_true")
    _add_engine_arg(e)
    e.set_defaults(func=_cmd_extract)

    v = subs.add_parser("validate", help="Validate a file against a template.")
    v.add_argument("file")
    v.add_argument("--template", required=True)
    v.add_argument("--json", action="store_true", help="emit JSON report to stdout")
    v.add_argument(
        "--fail-on",
        choices=["none", "cell", "structural"],
        default="structural",
        help="non-zero exit on errors at or above this severity (default: structural)",
    )
    _add_engine_arg(v)
    v.set_defaults(func=_cmd_validate)

    c = subs.add_parser("check", help="Extract + validate in one call.")
    c.add_argument("file")
    c.add_argument("--template", required=True)
    c.add_argument("--compact", action="store_true")
    _add_engine_arg(c)
    c.set_defaults(func=_cmd_check)

    s = subs.add_parser("stream", help="Stream JSONL records of one entity.")
    s.add_argument("file")
    s.add_argument("--template", required=True)
    s.add_argument("--entity", required=True)
    s.add_argument("--allow-partial", action="store_true", help="yield rows even when errors are present")
    _add_engine_arg(s)
    s.set_defaults(func=_cmd_stream)

    b = subs.add_parser("batch", help="Run check() over every supported spreadsheet in a directory.")
    b.add_argument("dir")
    b.add_argument("--template", required=True)
    b.add_argument("--out")
    b.add_argument("--report")
    _add_engine_arg(b)
    b.set_defaults(func=_cmd_batch)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
