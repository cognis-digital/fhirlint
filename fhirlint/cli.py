"""Command-line interface for FHIRLINT.

Examples:

    # validate a single resource, human-readable table
    python -m fhirlint validate patient.json

    # validate a bundle and emit machine-readable JSON (for CI piping)
    python -m fhirlint validate bundle.json --format json

    # validate several files at once
    python -m fhirlint validate a.json b.json c.json

    # read from stdin
    cat patient.json | python -m fhirlint validate -

Exit codes:
    0  no errors found (warnings/info allowed)
    1  one or more error-severity findings (fails CI gates)
    2  usage / file error
"""

from __future__ import annotations

import argparse
import json
import sys

from . import TOOL_NAME, TOOL_VERSION
from .core import lint_text, lint_file, has_errors, summarize, Finding


def _read_source(path: str) -> tuple[str, list[Finding]]:
    """Return (label, findings) for one source path ('-' = stdin)."""
    if path == "-":
        try:
            text = sys.stdin.read()
        except UnicodeDecodeError as exc:
            return "<stdin>", [Finding(
                "error", "encoding-error",
                f"stdin is not valid UTF-8: {exc.reason}", "<stdin>", 0,
            )]
        except OSError as exc:
            return "<stdin>", [Finding(
                "error", "io-error",
                f"could not read stdin: {exc}", "<stdin>", 0,
            )]
        return "<stdin>", lint_text(text)
    try:
        return path, lint_file(path)
    except FileNotFoundError:
        return path, [Finding("error", "file-not-found",
                              f"file not found: {path}", path, 0)]
    except OSError as exc:
        return path, [Finding("error", "io-error",
                              f"could not read {path}: {exc}", path, 0)]


def _print_table(label: str, findings: list[Finding]) -> None:
    if not findings:
        print(f"OK  {label}: no issues found")
        return
    print(f"--- {label} ---")
    for f in findings:
        loc = f"line {f.line}" if f.line else "line ?"
        sev = f.severity.upper().ljust(7)
        print(f"  {sev} {loc:>8}  {f.path}: {f.message}  [{f.code}]")
    counts = summarize(findings)
    print(f"  => {counts['error']} error(s), "
          f"{counts['warning']} warning(s), {counts['info']} info")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=TOOL_NAME,
        description="FHIRLINT - fast, JSON-native FHIR R4 resource/bundle "
                    "linter with line-level errors.",
        epilog="Examples:\n"
               "  python -m fhirlint validate patient.json\n"
               "  python -m fhirlint validate bundle.json --format json\n"
               "  cat patient.json | python -m fhirlint validate -\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version", action="version",
        version=f"{TOOL_NAME} {TOOL_VERSION}",
    )
    sub = parser.add_subparsers(dest="command")

    val = sub.add_parser(
        "validate",
        help="validate one or more FHIR R4 JSON files (use '-' for stdin)",
        description="Validate FHIR R4 resources/bundles and report findings.",
    )
    val.add_argument(
        "paths", nargs="+", metavar="FILE",
        help="FHIR JSON file(s) to validate; use '-' to read from stdin",
    )
    val.add_argument(
        "--format", choices=("table", "json"), default="table",
        help="output format (default: table)",
    )
    return parser


def main(argv=None) -> int:
    try:
        return _main(argv)
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 2
    except Exception as exc:  # pragma: no cover
        print(f"fhirlint: unexpected error: {exc}", file=sys.stderr)
        return 2


def _main(argv=None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 2

    if args.command == "validate":
        if not args.paths:
            print("fhirlint: no files specified", file=sys.stderr)
            return 2

        results = [_read_source(p) for p in args.paths]
        any_error = any(has_errors(f) for _, f in results)

        if args.format == "json":
            payload = {
                "tool": TOOL_NAME,
                "version": TOOL_VERSION,
                "files": [
                    {
                        "file": label,
                        "summary": summarize(findings),
                        "findings": [f.to_dict() for f in findings],
                    }
                    for label, findings in results
                ],
                "ok": not any_error,
            }
            print(json.dumps(payload, indent=2))
        else:
            for label, findings in results:
                _print_table(label, findings)
        return 1 if any_error else 0

    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
