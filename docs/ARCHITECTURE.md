# Architecture — migrisk

## Overview
migrisk reads a folder of sequential SQLite migration SQL files, parses DDL statements, builds a before/after schema model, and classifies risky operations. It is offline and stdlib-only.

## Components

### `src/migrisk/core.py`
- `Risk` enum: INFO, LOW, MEDIUM, HIGH, CRITICAL
- `Finding`, `Column`, `Table`, `Schema`, `MigrationPlan`, `ReviewResult` dataclasses
- `Schema.copy()` — deep copy of tables/views/columns
- SQL statement splitter (`_split_statements`)
- DDL regex patterns for CREATE/ALTER/DROP/PRBAMA

### `src/migrisk/analyzer.py`
- `_extract_column_defs()` — parses CREATE TABLE body into column tuples
- `_parse_one_column()` — parses a single column definition
- `_table_from_create()` — builds a `Table` from a CREATE TABLE statement
- `analyze_migration()` — main entry: parses file, applies statements to schema, runs risk analysis
- `_analyze_alter()` — checks ADD COLUMN (NOT NULL without DEFAULT) and DROP COLUMN (nonexistent)
- `_analyze_create_table()` — checks duplicate table creation

### `src/migrisk/cli.py`
- argparse CLI with `root`, `--format`, `--gate`
- `_scan_migrations()` — discovers SQL files in a directory
- Builds schema incrementally across files, exits 1 when findings meet or exceed gate

## Data flow
1. CLI discovers migration files sorted by name
2. For each file, `analyze_migration()` parses DDL and updates schema
3. Risk analysis pass checks each statement against the before schema
4. `ReviewResult` aggregates all findings across migrations
5. Output is rendered as text or JSON; exit code set by gate

## Design decisions
- **Stdlib only**: `re`, `pathlib`, `dataclasses` — no external dependencies.
- **Incremental schema**: each migration is applied to the schema produced by the previous one, mimicking real migration order.
- **Conservative view handling**: views are assumed to potentially reference any table, so dropping a table with an existing view is flagged HIGH.
- **Heuristic DDL parsing**: targeted at the most common SQLite migration patterns; not a full SQL parser.
