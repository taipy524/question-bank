"""High-risk semantic false positives must not enter normal suggestions."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import build_mapping as bm  # noqa: E402
import fixtures  # noqa: E402
import preview_import as pi  # noqa: E402
from common import load_internal_snapshot  # noqa: E402


def _run(tmp: Path, topics, rows):
    source = fixtures.make_source(tmp, topics=topics, dependencies=[], standards_items=[])
    snapshot = load_internal_snapshot(
        fixtures.make_snapshot(tmp, subject_name="数学", rows=rows)
    )
    return bm.build_mapping(source, snapshot)


class HighRiskTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_antonym_variant_is_high_risk(self):
        result, _ = _run(
            self.root / "antonym",
            [fixtures.topic("cnm_001", "正比例函数")],
            [
                {"internal_id": 1, "name": "数学", "parent_id": None},
                {"internal_id": 2, "name": "函数", "parent_id": 1},
                {"internal_id": 3, "name": "反比例函数", "parent_id": 2},
            ],
        )
        candidate = result["high_risk_candidates"][0]
        self.assertEqual(candidate["internal_id"], 3)
        self.assertIn("confusable_single_char", candidate["risk"])
        self.assertIsNone(result["external_topics"][0]["suggestion_internal_id"])
        self.assertEqual(result["stats"]["high_risk_pairs"], 1)
        self.assertEqual(result["stats"]["suggestion_nodes"], 0)
        self.assertEqual(result["split_candidates"], [])

    def test_sequence_variant_is_high_risk(self):
        result, _ = _run(
            self.root / "sequence",
            [fixtures.topic("cnm_001", "三元一次方程组")],
            [
                {"internal_id": 1, "name": "数学", "parent_id": None},
                {"internal_id": 2, "name": "方程与不等式", "parent_id": 1},
                {"internal_id": 3, "name": "二元一次方程组", "parent_id": 2},
            ],
        )
        self.assertEqual(result["high_risk_candidates"][0]["internal_id"], 3)
        self.assertIn("三->二", result["high_risk_candidates"][0]["risk"])

    def test_composite_topic_is_high_risk_without_equal_length(self):
        result, _ = _run(
            self.root / "composite",
            [fixtures.topic("cnm_001", "一次函数与二元一次方程组")],
            [
                {"internal_id": 1, "name": "数学", "parent_id": None},
                {"internal_id": 2, "name": "方程与不等式", "parent_id": 1},
                {"internal_id": 3, "name": "二元一次方程组", "parent_id": 2},
            ],
        )
        candidate = result["high_risk_candidates"][0]
        self.assertEqual(candidate["risk"], "composite_topic_contains_other_concept")
        self.assertIsNone(result["external_topics"][0]["suggestion_internal_id"])

    def test_safe_qualifier_is_not_high_risk(self):
        result, _ = _run(
            self.root / "safe",
            [fixtures.topic("cnm_001", "一元二次方程的概念")],
            [
                {"internal_id": 1, "name": "数学", "parent_id": None},
                {"internal_id": 2, "name": "方程与不等式", "parent_id": 1},
                {"internal_id": 3, "name": "一元二次方程", "parent_id": 2},
            ],
        )
        self.assertEqual(result["high_risk_candidates"], [])
        self.assertEqual(
            result["external_topics"][0]["suggestion_internal_id"], 3
        )

    def test_high_risk_never_in_preview_suggestions(self):
        result, _ = _run(
            self.root / "preview",
            [fixtures.topic("cnm_001", "正比例函数")],
            [
                {"internal_id": 1, "name": "数学", "parent_id": None},
                {"internal_id": 2, "name": "函数", "parent_id": 1},
                {"internal_id": 3, "name": "反比例函数", "parent_id": 2},
            ],
        )
        validation = vm_analyse(self.root / "preview", result)
        preview = pi.build_preview(result, validation, self.root / "preview" / "source")
        self.assertEqual(preview["direct_suggestions"], [])
        self.assertEqual(len(preview["high_risk_candidates"]), 1)
        self.assertEqual(preview["summary"]["confirmed_mappings"], 0)


def vm_analyse(root: Path, mapping):
    import validate_mapping as vm

    source = root / "source"
    snapshot = load_internal_snapshot(root / "internal_snapshot.json")
    return vm.analyse(source, snapshot, mapping)


if __name__ == "__main__":
    unittest.main()
