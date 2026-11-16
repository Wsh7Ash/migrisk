"""Migration file analyzer: parse DDL, build schema model, classify risk."""

from __future__ import annotations

import re
from pathlib import Path

from .core import (
    Column,
    Finding,
    MigrationPlan,
    Risk,
    Schema,
    Table,
    PRAGMA_RE,
    ALTER_TABLE_RE,
    CREATE_TABLE_RE,
    CREATE_VIEW_RE,
    DROP_TABLE_RE,
    DROP_VIEW_RE,
    parse_sql_file,
)


def _extract_column_defs(body: str) -> list[tuple[str, str, bool, str | None, bool]]:
    """Return list of (name, type, not_null, default, primary_key) from a CREATE TABLE body."""
    cols: list[tuple[str, str, bool, str | None, bool]] = []
    # Remove single-line comments
    clean = re.sub(r"--.*?$", "", body, flags=re.MULTILINE)
    # Split on top-level commas (not inside parentheses)
    depth = 0
    buf: list[str] = []
    for ch in clean:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            part = "".join(buf).strip()
            if part:
                cols.extend(_parse_one_column(part))
            buf = []
            continue
        buf.append(ch)
    if buf:
        part = "".join(buf).strip()
        if part:
            cols.extend(_parse_one_column(part))
    return cols


def _parse_one_column(stmt: str) -> list[tuple[str, str, bool, str | None, bool]]:
    """Parse a single column definition or constraint."""
    stmt = stmt.strip()
    if not stmt:
        return []
    low = stmt.lower()
    if low.startswith("primary key") or low.startswith("foreign key") or low.startswith(
        "unique") or low.startswith("check"):
        return []
    m = re.match(r"\"?([^\s(\"]+)\"?\s*(.*)?", stmt, re.IGNORECASE)
    if not m:
        return []
    name = m.group(1)
    rest = m.group(2) or ""
    not_null = bool(re.search(r"\bnot\s+null\b", rest, re.IGNORECASE))
    default_m = re.search(r"\bdefault\s+(.*?)(?:\s*$|\s|,)", rest, re.IGNORECASE)
    default = default_m.group(1).strip() if default_m else None
    if default and len(default) >= 2:
        if (default[0] == default[-1]) and default[0] in ('"', "'"):
            default = default[1:-1]
    pk = bool(re.search(r"\bprimary\s+key\b", rest, re.IGNORECASE))
    type_m = re.match(r"\s*(\w+)", rest)
    col_type = type_m.group(1) if type_m else ""
    return [(name, col_type, not_null, default, pk)]


def _table_from_create(stmt: str) -> Table | None:
    m = CREATE_TABLE_RE.search(stmt)
    if not m:
        return None
    name = Schema._strip_quotes(m.group(1))
    body = m.group(2)
    cols = _extract_column_defs(body)
    table = Table(name=name)
    for cname, ctype, nn, default, pk in cols:
        table.columns[cname] = Column(name=cname, type=ctype, not_null=nn,
                                      default=default, primary_key=pk)
    return table


def _add_alter_column(table: Table, stmt: str) -> None:
    m = ALTER_TABLE_RE.match(stmt)
    if not m:
        return
    table_name = m.group(1)
    rest = m.group(2).strip()
    low = rest.lower()
    if "add column" in low or low.startswith("add"):
        cm = re.search(r"add\s+column\s+\"?([^\s(\)]+)\"?", rest, re.IGNORECASE)
        if cm:
            cname = cm.group(1)
            type_m = re.search(r"\b(\w+)\b", rest[cm.end():], re.IGNORECASE)
            col_type = type_m.group(1) if type_m else ""
            not_null = bool(re.search(r"\bnot\s+null\b", rest, re.IGNORECASE))
            default_m = re.search(r"\bdefault\s+(.*?)(?:\s*$|\s)", rest, re.IGNORECASE)
            default = default_m.group(1).strip() if default_m else None
            table.columns[cname] = Column(name=cname, type=col_type, not_null=not_null,
                                          default=default)
    elif "drop column" in low or low.startswith("drop"):
        cm = re.search(r"drop\s+column\s+\"?([^\s(\)]+)\"?", rest, re.IGNORECASE)
        if cm:
            cname = cm.group(1)
            table.columns.pop(cname, None)


def analyze_migration(path: Path, before: Schema) -> MigrationPlan:
    statements = parse_sql_file(path)
    plan = MigrationPlan(file=path.name, statements=statements, before=before)
    after = before.copy()
    plan.after = after

    view_refs = _collect_view_references(statements, after)

    for stmt in statements:
        low = stmt.lower().strip()
        if low.startswith("create table"):
            t = _table_from_create(stmt)
            if t:
                # Don't add to after yet if it would be a dup; record first
                if t.name not in after.tables and t.name not in after.views:
                    after.tables[t.name] = t
                else:
                    # Duplicate: record but don't add to after
                    plan.findings.append(
                        Finding(file=plan.file, rule="duplicate-table",
                                risk=Risk.MEDIUM,
                                detail=f"CREATE TABLE {t.name!r} but table already exists in schema",
                                evidence=stmt[:120]))
        elif low.startswith("create view"):
            m = CREATE_VIEW_RE.search(stmt)
            if m:
                name = Schema._strip_quotes(m.group(1))
                if name not in after.views and name not in after.tables:
                    after.views[name] = Table(name=name)
        elif low.startswith("drop table"):
            m = DROP_TABLE_RE.search(stmt)
            if m:
                name = m.group(1)
                t = after.tables.pop(name, None)
                v = after.views.pop(name, None)
                if t is None and v is None:
                    plan.findings.append(
                        Finding(file=path.name, rule="drop-nonexistent",
                                risk=Risk.LOW,
                                detail=f"Attempted to drop {name!r} which does not exist in current schema",
                                evidence=stmt[:120]))
                else:
                    # Check if other views reference this table
                    for vname, v in after.views.items():
                        if _view_references_table(vname, name, after):
                            plan.findings.append(
                                Finding(file=path.name, rule="drop-referenced-table",
                                        risk=Risk.HIGH,
                                        detail=f"Dropping {name!r} which is referenced by view {vname!r}",
                                        evidence=f"view {vname} depends on {name}"))
        elif low.startswith("drop view"):
            m = DROP_VIEW_RE.search(stmt)
            if m:
                name = m.group(1)
                if name not in after.views:
                    plan.findings.append(
                        Finding(file=path.name, rule="drop-nonexistent-view",
                                risk=Risk.LOW,
                                detail=f"Attempted to drop view {name!r} which does not exist",
                                evidence=stmt[:120]))
                after.views.pop(name, None)
        elif low.startswith("alter table"):
            m = ALTER_TABLE_RE.match(stmt)
            if m:
                t = after.tables.get(m.group(1))
                if t is None:
                    t = after.views.get(m.group(1))
                if t is not None:
                    _add_alter_column(t, stmt)
                else:
                    plan.findings.append(
                        Finding(file=path.name, rule="alter-nonexistent",
                                risk=Risk.MEDIUM,
                                detail=f"ALTER TABLE on {m.group(1)!r} which does not exist in current schema",
                                evidence=stmt[:120]))
        elif low.startswith("pragma"):
            m = PRAGMA_RE.match(stmt)
            if m:
                key = m.group(1).lower()
                val = m.group(2).strip().strip(";")
                after.pragmas[key] = val

    # Risk analysis pass
    for stmt in statements:
        low = stmt.lower().strip()
        if low.startswith("alter table"):
            m = ALTER_TABLE_RE.match(stmt)
            if m:
                _analyze_alter(plan, m.group(1), m.group(2), before, after)
        elif low.startswith("create table"):
            _analyze_create_table(plan, stmt, after, before)
        elif low.startswith("pragma"):
            m = PRAGMA_RE.match(stmt)
            if m:
                key = m.group(1).lower()
                if key in ("foreign_keys", "recursive_triggers", "journal_mode",
                           "synchronous", "locking_mode", "cache_size"):
                    before_val = before.pragmas.get(key)
                    after_val = after.pragmas.get(key)
                    if before_val != after_val:
                        plan.findings.append(
                            Finding(file=path.name, rule="pragma-change",
                                    risk=Risk.LOW,
                                    detail=f"PRAGMA {key} changes from {before_val!r} to {after_val!r}",
                                    evidence=stmt[:120]))

    return plan


def _collect_view_references(statements: list[str], schema: Schema) -> dict[str, set[str]]:
    refs: dict[str, set[str]] = {}
    for stmt in statements:
        low = stmt.lower()
        if "create view" in low:
            m = CREATE_VIEW_RE.search(stmt)
            if m:
                vname = m.group(1)
                refs[vname] = _extract_table_refs_from_sql(stmt, schema)
    return refs


def _extract_table_refs_from_sql(stmt: str, schema: Schema) -> set[str]:
    found: set[str] = set()
    for name in list(schema.tables.keys()) + list(schema.views.keys()):
        if re.search(rf"\b{re.escape(name)}\b", stmt, re.IGNORECASE):
            found.add(name)
    return found


def _view_references_table(view_name: str, table_name: str, schema: Schema) -> bool:
    v = schema.views.get(view_name)
    if v is None:
        return False
    # For this reviewer, we assume views reference tables by name in their definition.
    # Since we don't store the full view SQL, we use a conservative heuristic:
    # if the view was created in the same migration set, check the create statement.
    # For simplicity, we mark a risk if the view exists at all when a table is dropped.
    # This is intentionally conservative.
    return True  # conservative: assume views may reference dropped tables


def _analyze_alter(plan: MigrationPlan, table_name: str, rest: str,
                   before: Schema, after: Schema) -> None:
    low = rest.lower()
    if "add column" in low:
        cm = re.search(r"add\s+column\s+\"?([^\s(\)]+)\"?", rest, re.IGNORECASE)
        if cm:
            cname = cm.group(1)
            if before and not before.column_exists(table_name, cname):
                after_t = after.tables.get(table_name) or after.views.get(table_name)
                col = after_t.columns.get(cname) if after_t else None
                if col and col.not_null and col.default is None:
                    plan.findings.append(
                        Finding(file=plan.file, rule="not-null-no-default",
                                risk=Risk.HIGH,
                                detail=f"Adding NOT NULL column {cname!r} without DEFAULT on {table_name!r}; existing rows would fail",
                                evidence=f"ALTER TABLE {table_name} ADD COLUMN {cname} ..."))
    elif "drop column" in low:
        cm = re.search(r"drop\s+column\s+\"?([^\s(\)]+)\"?", rest, re.IGNORECASE)
        if cm:
            cname = cm.group(1)
            if before and not before.column_exists(table_name, cname):
                plan.findings.append(
                    Finding(file=plan.file, rule="drop-nonexistent-column",
                            risk=Risk.MEDIUM,
                            detail=f"Attempting to drop column {cname!r} from {table_name!r} which does not exist in current schema",
                            evidence=f"ALTER TABLE {table_name} DROP COLUMN {cname}"))


def _analyze_create_table(plan: MigrationPlan, stmt: str, after: Schema, before: Schema | None = None) -> None:
    t = _table_from_create(stmt)
    if t is None:
        return
    # Check for duplicate table creation in the incoming before schema
    check_schema = before if before is not None else after
    if t.name in check_schema.tables or t.name in check_schema.views:
        plan.findings.append(
            Finding(file=plan.file, rule="duplicate-table",
                    risk=Risk.MEDIUM,
                    detail=f"CREATE TABLE {t.name!r} but table already exists in schema",
                    evidence=stmt[:120]))
