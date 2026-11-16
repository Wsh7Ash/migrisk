"""Tests for migration analysis and risk classification."""

from __future__ import annotations

from migrisk.analyzer import analyze_migration
from migrisk.core import Schema, Table, Column, Risk, Finding
from pathlib import Path
import tempfile


def test_add_not_null_column_no_default_high_risk():
    schema = Schema()
    schema.tables["users"] = Table(name="users")
    schema.tables["users"].columns["id"] = Column(name="id", primary_key=True)

    with tempfile.NamedTemporaryFile("w", suffix=".sql", delete=False,
                                     encoding="utf-8") as f:
        f.write("ALTER TABLE users ADD COLUMN email TEXT NOT NULL;\n")
        path = Path(f.name)

    plan = analyze_migration(path, schema)
    findings = [x for x in plan.findings if x.rule == "not-null-no-default"]
    assert len(findings) == 1
    assert findings[0].risk == Risk.HIGH
    Path(f.name).unlink()


def test_add_column_with_default_low_risk():
    schema = Schema()
    schema.tables["users"] = Table(name="users")
    schema.tables["users"].columns["id"] = Column(name="id", primary_key=True)

    with tempfile.NamedTemporaryFile("w", suffix=".sql", delete=False,
                                     encoding="utf-8") as f:
        f.write("ALTER TABLE users ADD COLUMN email TEXT NOT NULL DEFAULT '';\n")
        path = Path(f.name)

    plan = analyze_migration(path, schema)
    findings = [x for x in plan.findings if x.rule == "not-null-no-default"]
    assert len(findings) == 0
    Path(f.name).unlink()


def test_drop_column_that_does_not_exist_medium_risk():
    schema = Schema()
    schema.tables["users"] = Table(name="users")
    schema.tables["users"].columns["id"] = Column(name="id", primary_key=True)

    with tempfile.NamedTemporaryFile("w", suffix=".sql", delete=False,
                                     encoding="utf-8") as f:
        f.write("ALTER TABLE users DROP COLUMN bio;\n")
        path = Path(f.name)

    plan = analyze_migration(path, schema)
    findings = [x for x in plan.findings if x.rule == "drop-nonexistent-column"]
    assert len(findings) == 1
    assert findings[0].risk == Risk.MEDIUM
    Path(f.name).unlink()


def test_drop_referenced_table():
    schema = Schema()
    schema.tables["users"] = Table(name="users")
    schema.tables["users"].columns["id"] = Column(name="id", primary_key=True)
    schema.views["user_summary"] = Table(name="user_summary", is_view=True)

    with tempfile.NamedTemporaryFile("w", suffix=".sql", delete=False,
                                     encoding="utf-8") as f:
        f.write("DROP TABLE users;\n")
        path = Path(f.name)

    plan = analyze_migration(path, schema)
    findings = [x for x in plan.findings if x.rule == "drop-referenced-table"]
    # With conservative heuristic, view exists → flagged
    assert len(findings) >= 1
    Path(f.name).unlink()


def test_clean_create_table():
    schema = Schema()

    with tempfile.NamedTemporaryFile("w", suffix=".sql", delete=False,
                                     encoding="utf-8") as f:
        f.write("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL);\n")
        path = Path(f.name)

    plan = analyze_migration(path, schema)
    assert len(plan.findings) == 0
    assert "users" in plan.after.tables
    Path(f.name).unlink()


def test_pragma_change():
    schema = Schema()
    schema.pragmas["foreign_keys"] = "0"

    with tempfile.NamedTemporaryFile("w", suffix=".sql", delete=False,
                                     encoding="utf-8") as f:
        f.write("PRAGMA foreign_keys = ON;\n")
        path = Path(f.name)

    plan = analyze_migration(path, schema)
    findings = [x for x in plan.findings if x.rule == "pragma-change"]
    assert len(findings) == 1
    assert findings[0].risk == Risk.LOW
    Path(f.name).unlink()


def test_sequential_migrations():
    from migrisk.cli import _scan_migrations
    from migrisk.analyzer import analyze_migration

    schema = Schema()

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        (td / "001 Create users.sql").write_text(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL);\n", encoding="utf-8")
        (td / "002 Add email.sql").write_text(
            "ALTER TABLE users ADD COLUMN email TEXT NOT NULL DEFAULT '';\n", encoding="utf-8")
        (td / "003 Drop bio.sql").write_text(
            "ALTER TABLE users DROP COLUMN bio;\n", encoding="utf-8")

        files = _scan_migrations(td)
        assert len(files) == 3

        after = schema
        for f in files:
            plan = analyze_migration(f, after)
            assert plan.file == f.name
            after = plan.after

        # 003 should flag drop-nonexistent-column
        f003 = files[2]
        plan003 = analyze_migration(f003, schema)
        assert any(x.rule == "drop-nonexistent-column" for x in plan003.findings)
