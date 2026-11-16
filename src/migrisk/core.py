"""Core models: risk levels, findings, schema model, and report output."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class Risk(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class Finding:
    file: str
    rule: str
    risk: Risk
    detail: str
    evidence: str = ""


@dataclass
class Column:
    name: str
    type: str = ""
    not_null: bool = False
    default: str | None = None
    primary_key: bool = False


@dataclass
class Table:
    name: str
    columns: dict[str, Column] = field(default_factory=dict)
    indexes: set[str] = field(default_factory=set)
    is_view: bool = False


@dataclass
class Schema:
    tables: dict[str, Table] = field(default_factory=dict)
    views: dict[str, Table] = field(default_factory=dict)
    pragmas: dict[str, str] = field(default_factory=dict)

    def table_exists(self, name: str) -> bool:
        return name in self.tables or name in self.views

    def column_exists(self, table: str, column: str) -> bool:
        t = self.tables.get(table) or self.views.get(table)
        return t is not None and column in t.columns

    @staticmethod
    def _strip_quotes(name: str) -> str:
        return name.strip('"' + chr(39))

    def copy(self) -> Schema:
        return Schema(
            tables={
                name: Table(
                    name=t.name,
                    columns={cn: Column(name=cn, type=c.type, not_null=c.not_null,
                                        default=c.default, primary_key=c.primary_key)
                             for cn, c in t.columns.items()},
                    indexes=set(t.indexes),
                    is_view=t.is_view,
                )
                for name, t in self.tables.items()
            },
            views={
                name: Table(
                    name=t.name,
                    columns={cn: Column(name=cn, type=c.type, not_null=c.not_null,
                                        default=c.default, primary_key=c.primary_key)
                             for cn, c in t.columns.items()},
                    indexes=set(t.indexes),
                    is_view=t.is_view,
                )
                for name, t in self.views.items()
            },
            pragmas=dict(self.pragmas),
        )


@dataclass
class MigrationPlan:
    file: str
    statements: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    before: Schema = field(default_factory=Schema)
    after: Schema = field(default_factory=Schema)


@dataclass
class ReviewResult:
    root: str
    migrations: list[MigrationPlan] = field(default_factory=list)
    expectations: dict[str, Any] = field(default_factory=dict)

    @property
    def all_findings(self) -> list[Finding]:
        findings: list[Finding] = []
        for m in self.migrations:
            findings.extend(m.findings)
        return findings

    @property
    def max_risk(self) -> Risk:
        if not self.all_findings:
            return Risk.INFO
        order = [Risk.INFO, Risk.LOW, Risk.MEDIUM, Risk.HIGH, Risk.CRITICAL]
        return max(self.all_findings, key=lambda f: order.index(f.risk)).risk

    def to_text(self) -> str:
        lines: list[str] = []
        lines.append(f"migrisk report — {self.root}")
        lines.append("=" * 60)
        lines.append(f"Migrations reviewed: {len(self.migrations)}")
        lines.append(f"Total findings: {len(self.all_findings)}")
        lines.append(f"Max risk: {self.max_risk.value}")
        lines.append("")
        for m in self.migrations:
            lines.append(f"## {m.file}")
            lines.append(f"Statements: {len(m.statements)}")
            if not m.findings:
                lines.append("No risky patterns detected.")
            else:
                for risk in reversed(list(Risk)):
                    items = [f for f in m.findings if f.risk == risk]
                    if not items:
                        continue
                    lines.append(f"\n{risk.value.upper()} ({len(items)}):")
                    for f in items:
                        lines.append(f"  - {f.rule}: {f.detail}")
                        if f.evidence:
                            lines.append(f"    Evidence: {f.evidence}")
            lines.append("")
        return "\n".join(lines)

    def to_json(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "migrations": [
                {
                    "file": m.file,
                    "statement_count": len(m.statements),
                    "findings": [
                        {
                            "rule": f.rule,
                            "risk": f.risk.value,
                            "detail": f.detail,
                            "evidence": f.evidence,
                        }
                        for f in m.findings
                    ],
                }
                for m in self.migrations
            ],
            "max_risk": self.max_risk.value,
            "total_findings": len(self.all_findings),
        }


# Very small SQL DDL tokenizer/parser for the patterns migrisk cares about.
CREATE_TABLE_RE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?\"?([^\s\(]+)\"?\s*\((.*)\)",
    re.IGNORECASE | re.DOTALL,
)
ALTER_TABLE_RE = re.compile(
    r"ALTER\s+TABLE\s+\"?([^\s]+)\"?\s+(.*)", re.IGNORECASE | re.DOTALL,
)
DROP_TABLE_RE = re.compile(r"DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?\"?([^\s]+)\"?",
                           re.IGNORECASE)
CREATE_VIEW_RE = re.compile(r"CREATE\s+(?:OR\s+REPLACE\s+)?VIEW\s+\"?([^\s]+)\"?",
                            re.IGNORECASE)
DROP_VIEW_RE = re.compile(r"DROP\s+VIEW\s+(?:IF\s+EXISTS\s+)?\"?([^\s]+)\"?",
                          re.IGNORECASE)
PRAGMA_RE = re.compile(r"PRAGMA\s+(\w+)\s*(.*);?", re.IGNORECASE)
INDEX_REF_RE = re.compile(r"INDEX\s+\"?([^\s(\)]+)\"?", re.IGNORECASE)


def _split_statements(sql: str) -> list[str]:
    parts: list[str] = []
    buf: list[str] = []
    in_str = False
    str_ch = ""
    for ch in sql:
        if in_str:
            buf.append(ch)
            if ch == str_ch:
                in_str = False
            continue
        if ch in ("'", '"'):
            in_str = True
            str_ch = ch
            buf.append(ch)
            continue
        if ch == ";":
            parts.append("".join(buf).strip())
            buf = []
            continue
        buf.append(ch)
    if buf:
        parts.append("".join(buf).strip())
    return [p for p in parts if p]


def parse_sql_file(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    return [s for s in _split_statements(text) if s.strip()]
