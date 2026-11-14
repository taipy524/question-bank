#!/usr/bin/env python3
"""Export a read-only snapshot of existing knowledge points.

Two safe input modes are supported:

* ``--mysql-dump PATH``: parse a mysqldump file (default: the 2026-10-25 export
  kept outside the repository).  Nothing is executed against a database.
* ``--rows-json PATH``: consume an operator-provided JSON export produced by the
  read-only SQL documented in ``README.md``.

The script never writes to the database and only writes the snapshot below
``--out-dir``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    DEFAULT_INTERNAL_DUMP,
    DEFAULT_OUT_DIR,
    PrototypeError,
    stable_hash,
    write_json,
)


class SqlDumpError(PrototypeError):
    pass


def _find_insert_statement(text: str, table: str) -> str:
    marker = f"INSERT INTO `{table}` VALUES "
    start = text.find(marker)
    if start < 0:
        raise SqlDumpError(f"INSERT statement for {table} not found in dump")
    index = start + len(marker)
    in_string = False
    escaped = False
    while index < len(text):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == "'":
                in_string = False
        else:
            if char == "'":
                in_string = True
            elif char == ";":
                return text[start + len(marker) : index]
        index += 1
    raise SqlDumpError(f"unterminated INSERT statement for {table}")


def _parse_tuples(values: str) -> list[list[Any]]:
    rows: list[list[Any]] = []
    index = 0
    length = len(values)
    while index < length:
        while index < length and values[index] in " \t\r\n,":
            index += 1
        if index >= length:
            break
        if values[index] != "(":
            raise SqlDumpError(f"expected '(' at offset {index}")
        index += 1
        row: list[Any] = []
        current: list[str] = []
        in_string = False
        escaped = False
        quoted = False
        while index < length:
            char = values[index]
            if in_string:
                if escaped:
                    current.append(char)
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == "'":
                    in_string = False
                else:
                    current.append(char)
                index += 1
                continue
            if char == "'":
                in_string = True
                quoted = True
                index += 1
                continue
            if char in ",)":
                token = "".join(current).strip()
                if quoted:
                    row.append(token)
                elif token.upper() == "NULL":
                    row.append(None)
                elif re.fullmatch(r"-?\d+", token):
                    row.append(int(token))
                else:
                    row.append(token)
                current = []
                quoted = False
                index += 1
                if char == ")":
                    rows.append(row)
                    break
                continue
            current.append(char)
            index += 1
        else:
            raise SqlDumpError("unterminated tuple")
    return rows


def _load_dump_rows(path: Path) -> tuple[dict[int, dict[str, Any]], dict[int, str], str]:
    if not path.is_file():
        raise SqlDumpError(f"internal dump not found: {path}")
    text = path.read_text(encoding="utf-8", errors="replace")

    subject_rows = _parse_tuples(_find_insert_statement(text, "subjects"))
    subjects = {int(row[0]): str(row[1]) for row in subject_rows}

    kp_rows = _parse_tuples(_find_insert_statement(text, "knowledge_points"))
    knowledge_points: dict[int, dict[str, Any]] = {}
    for row in kp_rows:
        if len(row) < 5:
            raise SqlDumpError(f"unexpected knowledge_points row: {row!r}")
        internal_id = int(row[0])
        knowledge_points[internal_id] = {
            "internal_id": internal_id,
            "name": str(row[1]),
            "slug": str(row[2]),
            "subject_id": int(row[3]),
            "parent_id": None if row[4] is None else int(row[4]),
        }

    completed = re.search(r"-- Dump completed on ([^\n]+)", text)
    exported_at = completed.group(1).strip() if completed else "unknown"
    return knowledge_points, subjects, exported_at


def _build_snapshot(
    knowledge_points: dict[int, dict[str, Any]],
    subjects: dict[int, str],
    *,
    source: str,
    exported_at: str,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for internal_id in sorted(knowledge_points):
        row = knowledge_points[internal_id]
        parent_id = row["parent_id"]
        if parent_id is not None and parent_id not in knowledge_points:
            raise SqlDumpError(
                f"knowledge point {internal_id} references missing parent {parent_id}"
            )
        subject_name = subjects.get(row["subject_id"])
        if subject_name is None:
            raise SqlDumpError(
                f"knowledge point {internal_id} references missing subject {row['subject_id']}"
            )

        ancestors: list[str] = []
        cursor = parent_id
        seen: set[int] = set()
        while cursor is not None:
            if cursor in seen:
                raise SqlDumpError(f"parent cycle detected at knowledge point {cursor}")
            seen.add(cursor)
            ancestor = knowledge_points[cursor]
            ancestors.append(ancestor["name"])
            cursor = ancestor["parent_id"]
        ancestors.reverse()
        # The structural root usually repeats the subject name; keep one copy.
        if ancestors and ancestors[0] == subject_name:
            ancestors = ancestors[1:]

        rows.append(
            {
                "internal_id": internal_id,
                "name": row["name"],
                "slug": row["slug"],
                "subject_id": row["subject_id"],
                "subject_name": subject_name,
                "parent_id": parent_id,
                "parent_path": " > ".join([subject_name, *ancestors]),
            }
        )

    snapshot_hash = stable_hash(rows)
    return {
        "meta": {
            "source": source,
            "exported_at": exported_at,
            "row_count": len(rows),
            "snapshot_sha256": snapshot_hash,
            "fields": [
                "internal_id",
                "name",
                "slug",
                "subject_id",
                "subject_name",
                "parent_id",
                "parent_path",
            ],
        },
        "knowledge_points": rows,
    }


def _snapshot_from_rows_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("knowledge_points")
    if not isinstance(rows, list):
        raise SqlDumpError("--rows-json must contain a 'knowledge_points' array")
    normalized: dict[int, dict[str, Any]] = {}
    subjects: dict[int, str] = {}
    for row in rows:
        internal_id = int(row["internal_id"])
        subjects[int(row["subject_id"])] = str(row["subject_name"])
        normalized[internal_id] = {
            "internal_id": internal_id,
            "name": str(row["name"]),
            "slug": str(row["slug"]),
            "subject_id": int(row["subject_id"]),
            "parent_id": None if row.get("parent_id") is None else int(row["parent_id"]),
        }
    return _build_snapshot(
        normalized,
        subjects,
        source=f"operator JSON: {path}",
        exported_at=str(payload.get("exported_at", "unknown")),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mysql-dump", type=Path, default=DEFAULT_INTERNAL_DUMP)
    parser.add_argument("--rows-json", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args(argv)

    try:
        if args.rows_json is not None:
            snapshot = _snapshot_from_rows_json(args.rows_json)
        else:
            points, subjects, exported_at = _load_dump_rows(args.mysql_dump)
            snapshot = _build_snapshot(
                points,
                subjects,
                source=f"mysqldump: {args.mysql_dump}",
                exported_at=exported_at,
            )
    except PrototypeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    destination = args.out_dir / "internal_snapshot.json"
    write_json(destination, snapshot)
    print(f"wrote {destination} ({snapshot['meta']['row_count']} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
