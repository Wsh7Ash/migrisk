# Usage — migrisk

## Installation
```shell
pip install -e .
```
Or run directly with `PYTHONPATH=src python -m migrisk.cli`.

## Review a migration directory
```shell
migrisk migrations/
```

## Review a single migration file
```shell
migrisk 001_create_users.sql
```

## JSON output
```shell
migrisk migrations/ --format json
```

## Severity gate for CI
Exit code 1 if any finding at or above the given risk:
```shell
migrisk migrations/ --gate medium
migrisk migrations/ --gate high --format json
```

## Rules checked
| Rule | Risk | Meaning |
|---|---|---|
| not-null-no-default | HIGH | Adding NOT NULL column without DEFAULT on a non-empty table |
| drop-nonexistent-column | MEDIUM | Attempting to drop a column that doesn't exist |
| drop-nonexistent | LOW | Attempting to drop a table that doesn't exist |
| drop-nonexistent-view | LOW | Attempting to drop a view that doesn't exist |
| drop-referenced-table | HIGH | Dropping a table that has views (conservative) |
| alter-nonexistent | MEDIUM | ALTER TABLE on a table that doesn't exist |
| duplicate-table | MEDIUM | CREATE TABLE when table already exists |
| pragma-change | LOW | PRAGMA value changes from previous state |

## Files accepted
- `.sql` files in a directory (sorted by name)
- Single `.sql` files
- Files named with `migration` prefix and `.sql` suffix

## Schema simulation
migrisk builds a before/after schema model as it processes each migration in order. The before schema for migration N is the after schema from migration N-1.
