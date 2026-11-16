"""Command-line interface for migrisk."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .analyzer import analyze_migration
from .core import Risk, ReviewResult, Schema, parse_sql_file


def _scan_migrations(root: Path) -> list[Path]:
    files: list[Path] = []
    if root.is_file():
        files.append(root)
    else:
        for p in sorted(root.iterdir()):
            if p.is_file() and p.suffix.lower() in (".sql", ".sqlite", ".migrations.sql"):
                files.append(p)
            elif p.is_file() and p.name.lower().startswith("migration") and p.suffix == ".sql":
                files.append(p)
    return sorted(files, key=lambda p: p.name.lower())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="migrisk",
        description="SQLite migration reviewer with risk classification",
    )
    parser.add_argument(
        "root",
        nargs="?",
        help="Path to a migration SQL file or a folder of migration files",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format",
    )
    parser.add_argument(
        "--gate",
        choices=["info", "low", "medium", "high", "critical"],
        default="medium",
        help="Exit with code 1 if any finding at or above this risk",
    )
    args = parser.parse_args(argv)

    if not args.root:
        parser.print_help()
        return 2

    root = Path(args.root)
    if not root.exists():
        print(f"migrisk: path not found: {root}", file=sys.stderr)
        return 2

    files = _scan_migrations(root)
    if not files:
        print(f"migrisk: no migration files found in {root}", file=sys.stderr)
        return 2

    result = ReviewResult(root=str(root))
    schema: dict[str, object] = {}  # not used; build incrementally
    current_schema = None  # type: Schema | None

    for f in files:
        if current_schema is None:
            current_schema = Schema()
        plan = analyze_migration(f, current_schema)
        result.migrations.append(plan)
        current_schema = plan.after

    gate = Risk(args.gate)
    if result.all_findings and any(
        f.risk.value == gate.value or _risk_above(f.risk, gate)
        for f in result.all_findings
    ):
        if args.format == "json":
            import json
            print(json.dumps(result.to_json(), indent=2))
        else:
            print(result.to_text())
        return 1

    if args.format == "json":
        import json
        print(json.dumps(result.to_json(), indent=2))
    else:
        print(result.to_text())
    return 0


def _risk_above(finding_risk: Risk, gate: Risk) -> bool:
    order = [Risk.INFO, Risk.LOW, Risk.MEDIUM, Risk.HIGH, Risk.CRITICAL]
    return order.index(finding_risk) > order.index(gate)


if __name__ == "__main__":
    raise SystemExit(main())
