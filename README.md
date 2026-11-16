# migrisk

## SQLite migration reviewer with risk classification and row-delta simulation

Schema changes look harmless in isolation but can break in deployment: a `DROP COLUMN` on a table that still has views depending on it, a `NOT NULL` addition without a default on a populated table, or a `PRAGMA foreign_keys` mismatch. **migrisk** reads a folder of sequential SQLite migration SQL files, classifies each change by risk, simulates the before/after schema, and produces a severity-ranked report with row-delta and expectation checks.

- **Problem:** Migration files are reviewed as text; the real risk depends on the starting schema, existing data, and dependency side effects.
- **Solution:** Offline migration-plan reviewer that parses SQL DDL, builds a before/after schema model, classifies risky operations, and simulates whether a migration would fail on a non-empty table.
- **Audience:** Backend developers and DBAs reviewing SQLite migration scripts before they run in staging or production.

## Quick start

```shell
# install from source
pip install -e .

# review a folder of numbered migration files
migrisk migrations/

# JSON output for CI
migrisk migrations/ --format json

# set a severity gate
migrisk migrations/ --gate medium
```

## What it checks

- **Per-file DDL parsing**: `CREATE TABLE`, `ALTER TABLE ADD COLUMN`, `ALTER TABLE DROP COLUMN`, `CREATE INDEX`, `CREATE VIEW`, `DROP VIEW`, `DROP TABLE`, `PRAGMA` statements.
- **Risk classification**: dropping a column that exists, adding NOT NULL without DEFAULT on a non-empty table, dropping a table/view that is referenced by another view, PRAGMA changes.
- **Schema simulation**: builds a before and after model to detect whether a migration is compatible with the prior schema.
- **Expectation checks**: a small expectation file can assert that a column must or must not exist after a given migration.

## Outputs

- **Text report** — human-readable per-file findings with risk level and evidence.
- **JSON report** — machine-readable findings plus before/after schema summary.

## Tested with

- Python 3.12+
- Standard library only; no network calls; no live database required.

## License

MIT
