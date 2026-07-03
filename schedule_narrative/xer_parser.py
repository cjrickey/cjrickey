"""
Generic Primavera P6 XER file parser.

XER format: tab-delimited text.
  %T <table_name>       starts a new table block
  %F <field1> <field2>  header row (field names) for that table
  %R <val1> <val2>      one data row for that table
Tables repeat throughout the file (not just once), so a table name can
appear multiple times -- we append rows across all occurrences.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class XerFile:
    tables: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    header: dict[str, str] = field(default_factory=dict)

    def get(self, table_name: str) -> list[dict[str, str]]:
        return self.tables.get(table_name, [])


def parse_xer(path: str) -> XerFile:
    with open(path, encoding="utf-8", errors="replace") as f:
        # XER uses \r\n line endings but content can contain embedded \n in
        # some memo fields -- splitting on \n and stripping \r is safe for
        # all the structural tables we care about (TASK, PROJECT, PROJWBS,
        # TASKPRED, CALENDAR). Memo/notebook tables are more fragile and
        # we don't rely on them here.
        raw_lines = f.read().split("\n")

    xer = XerFile()
    current_table: Optional[str] = None
    current_fields: list[str] = []

    for raw_line in raw_lines:
        line = raw_line.rstrip("\r")
        if not line:
            continue
        marker, _, rest = line.partition("\t")

        if marker == "ERMHDR":
            parts = line.split("\t")
            xer.header = {
                "version": parts[1] if len(parts) > 1 else "",
                "export_date": parts[2] if len(parts) > 2 else "",
                "project_name": parts[3] if len(parts) > 3 else "",
                "exported_by": parts[5] if len(parts) > 5 else "",
            }
            continue

        if marker == "%T":
            current_table = rest.strip()
            xer.tables.setdefault(current_table, [])
            current_fields = []
            continue

        if marker == "%F":
            current_fields = rest.split("\t")
            continue

        if marker == "%R":
            if current_table is None:
                continue
            values = rest.split("\t")
            # pad/truncate defensively -- real-world exports sometimes have
            # trailing-empty-field truncation
            row = {}
            for i, fname in enumerate(current_fields):
                row[fname] = values[i] if i < len(values) else ""
            xer.tables[current_table].append(row)
            continue

    return xer


def parse_p6_datetime(value: str) -> Optional[datetime]:
    """P6 dates look like '2025-05-09 08:00' or '2025-05-09'. Empty -> None."""
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


if __name__ == "__main__":
    import sys
    xer = parse_xer(sys.argv[1])
    print("Header:", xer.header)
    print("Tables found:")
    for name, rows in xer.tables.items():
        print(f"  {name}: {len(rows)} rows")
