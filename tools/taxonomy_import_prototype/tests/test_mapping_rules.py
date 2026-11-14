"""Mapping rule tests on a synthetic dataset with every cardinality shape."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import build_mapping as bm  # noqa: E402
import fixtures  # noqa: E402
from common import load_internal_snapshot  # noqa: E402


class MappingRuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = fixtures.make_source(
            self.root,
            topics=fixtures.mapping_topics(),
            dependencies=fixtures.mapping_dependencies(),
            standards_items=fixtures.mapping_standards(),
        )
        self.snapshot_path = fixtures.make_snapshot(
            self.root, subject_name="数学", rows=fixtures.mapping_snapshot_rows()
        )
        self.snapshot = load_internal_snapshot(self.snapshot_path)
        self.result, _ = bm.build_mapping(self.source, self.snapshot)
        self.by_external = {
            row["external_id"]: row for row in self.result["external_topics"]
        }

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_all_external_topics_present_once(self):
        ids = [row["external_id"] for row in self.result["external_topics"]]
        self.assertEqual(len(ids), 9)
        self.assertEqual(len(ids), len(set(ids)))

    def test_exact_one_to_one(self):
        row = self.by_external["cnm_005"]
        self.assertEqual(row["match_type"], "exact")
        self.assertEqual(row["best_internal_id"], 9)
        self.assertEqual(row["review_status"], "pending_review")

    def test_second_exact_one_to_one(self):
        row = self.by_external["cnm_009"]
        self.assertEqual(row["match_type"], "exact")
        self.assertEqual(row["best_internal_id"], 7)

    def test_one_to_many_component(self):
        self.assertEqual(self.by_external["cnm_003"]["match_type"], "one_to_many")
        self.assertEqual(self.by_external["cnm_004"]["match_type"], "one_to_many")
        self.assertEqual(self.by_external["cnm_003"]["component_shape"], "1-N")

    def test_many_to_one_component(self):
        row = self.by_external["cnm_007"]
        self.assertEqual(row["match_type"], "many_to_one")
        self.assertEqual(row["component_shape"], "N-1")
        self.assertEqual(len(row["candidates"]), 2)

    def test_many_to_many_component(self):
        self.assertEqual(self.by_external["cnm_001"]["match_type"], "many_to_many")
        self.assertEqual(self.by_external["cnm_002"]["match_type"], "many_to_many")
        self.assertEqual(self.by_external["cnm_001"]["component_id"], self.by_external["cnm_002"]["component_id"])

    def test_new_topic_has_no_confidence(self):
        row = self.by_external["cnm_008"]
        self.assertEqual(row["match_type"], "new_topic")
        self.assertIsNone(row["confidence"])
        self.assertIsNone(row["best_internal_id"])
        self.assertEqual(row["candidates"], [])

    def test_exact_name_conflict_is_flagged(self):
        row = self.by_external["cnm_006"]
        self.assertEqual(row["match_type"], "exact")
        self.assertTrue(row["candidates"][0]["conflict"])
        self.assertEqual(row["candidates"][0]["confidence"], 0.5)
        self.assertEqual(self.result["stats"]["name_conflict_externals"], 1)

    def test_confusable_semantic_variant_is_high_risk(self):
        root = Path(self.tmp.name) / "risk"
        source = fixtures.make_source(
            root,
            topics=[fixtures.topic("cnm_001", "反比例函数")],
            dependencies=[],
            standards_items=[],
        )
        snapshot = load_internal_snapshot(
            fixtures.make_snapshot(
                root,
                subject_name="数学",
                rows=[
                    {"internal_id": 1, "name": "数学", "parent_id": None},
                    {"internal_id": 2, "name": "函数", "parent_id": 1},
                    {"internal_id": 3, "name": "正比例函数", "parent_id": 2},
                ],
            )
        )
        result, _ = bm.build_mapping(source, snapshot)
        topic = result["external_topics"][0]
        self.assertEqual(topic["match_type"], "semantic")
        candidate = topic["candidates"][0]
        self.assertEqual(candidate["risk"], "confusable_single_char:反->正")
        self.assertTrue(candidate["high_risk"])
        self.assertIsNone(topic["suggestion_internal_id"])
        self.assertEqual(result["stats"]["pairs_semantic_risk"], 1)
        self.assertEqual(result["stats"]["high_risk_pairs"], 1)

    def test_component_statistics_do_not_double_count(self):
        shapes = self.result["stats"]["components_by_shape"]
        self.assertEqual(shapes, {"1-1": 3, "1-N": 1, "N-1": 1, "N-M": 1})
        self.assertEqual(sum(shapes.values()), self.result["stats"]["components_total"])
        self.assertEqual(self.result["stats"]["pairs_total"], 10)
        self.assertEqual(self.result["stats"]["pairs_exact"], 7)
        self.assertEqual(self.result["stats"]["pairs_semantic"], 3)

    def test_pairs_are_deduplicated(self):
        pairs = [
            (row["external_id"], candidate["internal_id"])
            for row in self.result["external_topics"]
            for candidate in row["candidates"]
        ]
        self.assertEqual(len(pairs), len(set(pairs)))

    def test_internal_duplicate_and_unmatched(self):
        self.assertEqual(self.result["stats"]["duplicate_internal_pairs"], 1)
        self.assertGreater(self.result["stats"]["internal_unmatched"], 0)
        self.assertEqual(self.result["stats"]["merge_candidates"], 1)


if __name__ == "__main__":
    unittest.main()
