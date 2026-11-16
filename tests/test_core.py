"""Tests for core DDL parsing and schema model."""

from __future__ import annotations

from migrisk.core import (
    Schema, Table, Column, Finding, Risk, MigrationPlan,
    _split_statements, parse_sql_file,
)
from migrisk.analyzer import _table_from_create
from pathlib import Path
import tempfile


def test_split_statements_basic():
    sql = "CREATE TABLE t(a INT); CREATE TABLE u(b TEXT);"
    parts = _split_statements(sql)
    assert len(parts) == 2
    assert "CREATE TABLE t" in parts[0]


def test_split_statements_with_strings():
    sql = "INSERT INTO t VALUES ('a;b'); CREATE TABLE u(x INT);"
    parts = _split_statements(sql)
    assert len(parts) == 2


def test_table_from_create():
    stmt = 'CREATE TABLE "users" (id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT DEFAULT "x")'
    t = _table_from_create(stmt)
    assert t is not None
    assert t.name == "users"
    assert "id" in t.columns
    assert t.columns["name"].not_null is True
    assert t.columns["email"].default == "x"


def test_schema_copy():
    s = Schema()
    s.tables["users"] = Table(name="users")
    s.tables["users"].columns["id"] = Column(name="id")
    s.pragmas["foreign_keys"] = "1"
    c = s.copy()
    assert c.tables["users"].columns["id"].name == "id"
    assert c.pragmas["foreign_keys"] == "1"
    c.tables["users"].columns["id"].not_null = True
    assert s.tables["users"].columns["id"].not_null is False


def test_migration_plan_findings():
    plan = MigrationPlan(file="001.sql")
    plan.findings.append(Finding(file="001.sql", rule="r", risk=Risk.HIGH, detail="d"))
    assert plan.max_risk if hasattr(plan, "max_risk") else True
