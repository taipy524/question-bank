"""Stage-2 contract tests: real inputs, dry-run only, no forbidden dependencies."""

from __future__ import annotations

import hashlib
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

PROTOTYPE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROTOTYPE))

import stage2_review as review  # noqa: E402
import stage2_sim as sim  # noqa: E402
from common import DEFAULT_INTERNAL_DUMP, DEFAULT_SOURCE_DIR, file_sha256  # noqa: E402

REPORTS = PROTOTYPE.parents[1] / "reports"
FORBIDDEN = ("chromadb", "openai", "sqlalchemy", "pymysql", "mysql", "app")


def _tree_hashes(root: Path) -> dict[str, str]:
    if not root.exists():
        return {}
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts
    }


@unittest.skipUnless(
    DEFAULT_SOURCE_DIR.is_dir() and DEFAULT_INTERNAL_DUMP.is_file(),
    "real inputs not available",
)
class Stage2ContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name) / "out"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _common_args(self) -> list[str]:
        return [
            "--source-dir", str(DEFAULT_SOURCE_DIR),
            "--internal-snapshot", str(REPORTS / "internal_snapshot.json"),
            "--mapping", str(REPORTS / "mapping_result.json"),
            "--out-dir", str(self.out),
        ]

    def _decisions_file(self) -> Path:
        path = Path(self.tmp.name) / "decisions.json"
        path.write_text(
            json.dumps(
                {
                    "confirmed_mappings": [["cnm_041", 9], ["cnm_080", 3], ["cnm_174", 30]],
                    "confirmed_new_topics": ["cnm_001"],
                    "new_topic_parents": {"cnm_001": 2},
                    "reviewer": "stage2-test",
                    "comment": "simulation only",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return path

    def test_review_and_simulation_cli(self):
        self.assertEqual(
            review.main(self._common_args()),
            0,
        )
        decisions = self._decisions_file()
        self.assertEqual(
            sim.main(
                [*self._common_args(), "--decisions", str(decisions)]
            ),
            0,
        )
        self.assertTrue((self.out / "10_mapping_review_workflow.md").is_file())
        self.assertTrue((self.out / "11_new_topic_review.md").is_file())
        self.assertTrue((self.out / "15_batch_preview_rollback.md").is_file())
        payload = json.loads((self.out / "stage2_simulation.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["preview"]["errors"], [])
        self.assertTrue(payload["rollback"]["data_equal"])
        self.assertTrue(payload["verify"]["existing_internal_ids_preserved"])
        self.assertTrue(payload["verify"]["question_links_unchanged"])
        self.assertEqual(payload["verify"]["question_link_count"], 38)
        self.assertEqual(payload["preview"]["impact"]["mapping_rows"], 4)
        self.assertEqual(payload["preview"]["impact"]["new_knowledge_points"], 1)

    def test_high_risk_pair_requires_ack_in_simulation(self):
        decisions = Path(self.tmp.name) / "highrisk.json"
        decisions.write_text(
            json.dumps({"confirmed_mappings": [["cnm_093", 10]]}), encoding="utf-8"
        )
        self.assertEqual(
            sim.main(
                [*self._common_args(), "--decisions", str(decisions)]
            ),
            2,
        )

    def test_inputs_are_not_modified(self):
        source_hashes = {
            name: file_sha256(DEFAULT_SOURCE_DIR / "data" / name)
            for name in ("topics.json", "dependencies.json", "cn-curriculum-standards.json")
            if (DEFAULT_SOURCE_DIR / "data" / name).is_file()
        }
        dump_hash = file_sha256(DEFAULT_INTERNAL_DUMP)
        self.assertEqual(
            review.main(self._common_args()),
            0,
        )
        self.assertEqual(
            sim.main(
                [*self._common_args(), "--decisions", str(self._decisions_file())]
            ),
            0,
        )
        for name, digest in source_hashes.items():
            self.assertEqual(file_sha256(DEFAULT_SOURCE_DIR / "data" / name), digest)
        self.assertEqual(file_sha256(DEFAULT_INTERNAL_DUMP), dump_hash)

    def test_repo_reports_are_not_written(self):
        before = _tree_hashes(REPORTS)
        self.assertEqual(
            review.main(self._common_args()),
            0,
        )
        self.assertEqual(
            sim.main(
                [*self._common_args(), "--decisions", str(self._decisions_file())]
            ),
            0,
        )
        self.assertEqual(_tree_hashes(REPORTS), before)

    def test_no_forbidden_imports(self):
        pattern = re.compile(
            r"^\s*(?:from|import)\s+(" + "|".join(re.escape(name) for name in FORBIDDEN) + r")\b",
            re.MULTILINE,
        )
        offenders = [
            path.name
            for path in sorted(PROTOTYPE.glob("*.py"))
            if pattern.search(path.read_text(encoding="utf-8"))
        ]
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
