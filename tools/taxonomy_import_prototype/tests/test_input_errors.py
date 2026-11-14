"""Invalid or missing inputs must fail loudly, never partially write."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import build_mapping as bm  # noqa: E402
import export_internal as ei  # noqa: E402
import inspect_source as ins  # noqa: E402
import preview_import as pi  # noqa: E402
import validate_mapping as vm  # noqa: E402
import validate_source as vs  # noqa: E402
from common import PrototypeError, load_internal_snapshot, load_source  # noqa: E402


class InputErrorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_missing_source_dir(self):
        missing = self.root / "missing-source"
        self.assertEqual(ins.main(["--source-dir", str(missing), "--out-dir", str(self.root / "o")]), 2)
        self.assertEqual(vs.main(["--source-dir", str(missing), "--out-dir", str(self.root / "o")]), 2)
        with self.assertRaises(PrototypeError):
            load_source(missing)

    def test_invalid_json(self):
        source = self.root / "bad"
        (source / "data").mkdir(parents=True)
        (source / "data" / "topics.json").write_text("{not json", encoding="utf-8")
        with self.assertRaises(PrototypeError):
            load_source(source)

    def test_snapshot_duplicate_ids(self):
        path = self.root / "snapshot.json"
        row = {
            "internal_id": 1,
            "name": "root",
            "slug": "root",
            "subject_id": 1,
            "subject_name": "数学",
            "parent_id": None,
            "parent_path": "数学",
        }
        path.write_text(
            json.dumps({"meta": {}, "knowledge_points": [row, dict(row)]}, ensure_ascii=False),
            encoding="utf-8",
        )
        with self.assertRaises(PrototypeError):
            load_internal_snapshot(path)

    def test_build_mapping_missing_snapshot(self):
        self.assertEqual(
            bm.main(["--source-dir", str(self.root / "missing"), "--internal-snapshot", str(self.root / "nope.json"), "--out-dir", str(self.root / "o")]),
            2,
        )

    def test_validate_mapping_missing_mapping(self):
        self.assertEqual(
            vm.main(["--source-dir", str(self.root / "missing"), "--mapping", str(self.root / "nope.json"), "--out-dir", str(self.root / "o")]),
            2,
        )

    def test_preview_missing_mapping(self):
        self.assertEqual(
            pi.main(["--source-dir", str(self.root / "missing"), "--mapping", str(self.root / "nope.json"), "--out-dir", str(self.root / "o")]),
            2,
        )

    def test_export_without_input(self):
        self.assertEqual(
            ei.main(["--mysql-dump", str(self.root / "nope.sql"), "--out-dir", str(self.root / "o")]),
            2,
        )


if __name__ == "__main__":
    unittest.main()
