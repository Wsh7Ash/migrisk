# Contributing

## Setup
```shell
pip install -e ".[dev]"
```

## Running tests
```shell
PYTHONPATH=src python -m pytest tests/ -v
```

## Adding a risk rule
1. Add the rule name and risk level in `src/migrisk/core.py` (via `Finding` construction sites in `analyzer.py`).
2. Add detection logic in `src/migrisk/analyzer.py`.
3. Add a test in `tests/test_analyzer.py` with a temp SQL file.
4. Update `docs/USAGE.md` rules table.

## Design notes
- Keep the runtime stdlib-only.
- Keep the DDL parser heuristic and targeted at common SQLite migration patterns.
- Keep schema simulation incremental across migrations.
