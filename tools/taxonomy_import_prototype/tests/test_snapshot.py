"""Internal snapshot tests against the read-only 2026-10-25 export."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import export_internal as ei  # noqa: E402
from common import DEFAULT_INTERNAL_DUMP  # noqa: E402


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@unittest.skipUnless(DEFAULT_INTERNAL_DUMP.is_file(), "internal dump not available")
class SnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_snapshot_shape(self):
        self.assertEqual(ei.main(["--out-dir", str(self.out)]), 0)
        payload = json.loads((self.out / "internal_snapshot.json").read_text(encoding="utf-8"))
        rows = payload["knowledge_points"]
        self.assertEqual(payload["meta"]["row_count"], 62)
        self.assertEqual(len(rows), 62)
        by_id = {row["internal_id"]: row for row in rows}
        roots = [row for row in rows if row["parent_id"] is None]
        self.assertEqual(len(roots), 1)
        self.assertEqual(roots[0]["name"], "初三数学")
        categories = [row for row in rows if row["parent_id"] == roots[0]["internal_id"]]
        self.assertEqual(len(categories), 7)
        leaves = [row for row in rows if row["parent_id"] not in {roots[0]["internal_id"], None}]
        self.assertEqual(len(leaves), 54)
        self.assertEqual(len({(row["subject_id"], row["slug"]) for row in rows}), 62)
        self.assertEqual(by_id[2]["parent_path"], "初三数学")
        self.assertEqual(by_id[3]["parent_path"], "初三数学 > 数与式")
        self.assertEqual(len(payload["meta"]["snapshot_sha256"]), 64)

    def test_snapshot_is_deterministic(self):
        self.assertEqual(ei.main(["--out-dir", str(self.out / "a")]), 0)
        self.assertEqual(ei.main(["--out-dir", str(self.out / "b")]), 0)
        self.assertEqual(
            _sha(self.out / "a" / "internal_snapshot.json"),
            _sha(self.out / "b" / "internal_snapshot.json"),
        )

    def test_snapshot_source_is_unchanged(self):
        before = _sha(DEFAULT_INTERNAL_DUMP)
        self.assertEqual(ei.main(["--out-dir", str(self.out)]), 0)
        self.assertEqual(_sha(DEFAULT_INTERNAL_DUMP), before)

    def test_missing_dump_returns_error(self):
        self.assertEqual(ei.main(["--mysql-dump", str(self.out / "missing.sql"), "--out-dir", str(self.out)]), 2)

    def test_malformed_dump_returns_error(self):
        bad = self.out / "bad.sql"
        bad.write_text("not a dump", encoding="utf-8")
        self.assertEqual(ei.main(["--mysql-dump", str(bad), "--out-dir", str(self.out)]), 2)


if __name__ == "__main__":
    unittest.main()
