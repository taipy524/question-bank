"""In-memory stage-2 import/rollback simulation tests (synthetic data)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import build_mapping as bm  # noqa: E402
import fixtures  # noqa: E402
import stage2_sim as sim  # noqa: E402
from common import load_internal_snapshot, load_source  # noqa: E402


class Stage2SimulatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source_dir = fixtures.make_source(
            self.root,
            topics=fixtures.mapping_topics(),
            dependencies=fixtures.mapping_dependencies(),
            standards_items=fixtures.mapping_standards(),
        )
        self.snapshot = load_internal_snapshot(
            fixtures.make_snapshot(self.root, subject_name="数学", rows=fixtures.mapping_snapshot_rows())
        )
        self.mapping, _ = bm.build_mapping(self.source_dir, self.snapshot)
        self.source = load_source(self.source_dir)
        self.sim = sim.Stage2Simulator(self.snapshot, self.mapping, self.source, [])
        self.decisions = {
            "confirmed_mappings": [("cnm_001", 3), ("cnm_002", 4)],
            "confirmed_new_topics": ["cnm_008"],
            "new_topic_parents": {"cnm_008": 2},
            "reviewer": "tester",
            "comment": "synthetic",
        }

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_preview_counts(self):
        preview = self.sim.preview(self.decisions)
        self.assertEqual(preview["errors"], [])
        self.assertEqual(len(preview["mapping_rows"]), 3)
        self.assertEqual(len(preview["new_knowledge_points"]), 1)
        self.assertEqual(len(preview["prerequisite_rows"]), 1)  # cnm_001 -> cnm_002
        self.assertEqual(len(preview["standard_rows"]), 2)  # exact + inferred
        self.assertEqual(preview["impact"]["question_links"], 0)

    def test_cross_stage_edges_are_not_internalised(self):
        preview = self.sim.preview(self.decisions)
        external_ids = {
            (row["external_topic"], row["external_prerequisite"])
            for row in preview["prerequisite_rows"]
        }
        self.assertNotIn(("cnm_001", "cnm_p001"), external_ids)
        self.assertNotIn(("cnm_s001", "cnm_001"), external_ids)

    def test_execute_preserves_ids_and_question_links(self):
        before_ids = set(self.sim.internal_ids())
        before_links = list(self.sim.state["question_knowledge_points"])
        batch = self.sim.execute(self.decisions)
        self.assertEqual(batch["status"], "applied")
        self.assertGreater(batch["change_count"], 0)
        verify = self.sim.verify()
        self.assertTrue(verify["existing_internal_ids_preserved"])
        self.assertTrue(verify["question_links_unchanged"])
        self.assertTrue(before_ids <= set(self.sim.internal_ids()))
        self.assertEqual(before_links, self.sim.state["question_knowledge_points"])

    def test_rollback_restores_exact_state(self):
        before = self.sim.data_hash()
        batch = self.sim.execute(self.decisions)
        result = self.sim.rollback(batch["id"])
        self.assertTrue(result["data_equal"])
        self.assertEqual(self.sim.data_hash(), before)
        self.assertEqual(result["before_hash"], before)
        self.assertEqual(self.sim.verify()["question_links_unchanged"], True)

    def test_idempotent_execution(self):
        self.sim.execute(self.decisions)
        before = self.sim.data_hash()
        second = self.sim.execute(self.decisions)
        self.assertEqual(second["change_count"], 0)
        self.assertEqual(self.sim.data_hash(), before)

    def test_high_risk_requires_acknowledgement(self):
        with mock.patch.object(sim, "HIGH_RISK_PAIRS", {("cnm_001", 3)}):
            preview = self.sim.preview({"confirmed_mappings": [("cnm_001", 3)]})
            self.assertTrue(any("high-risk" in item for item in preview["errors"]))
            with self.assertRaises(sim.SimulationError):
                self.sim.execute({"confirmed_mappings": [("cnm_001", 3)]})
            acknowledged = {
                "confirmed_mappings": [("cnm_001", 3)],
                "acknowledged_high_risk": [("cnm_001", 3)],
            }
            self.assertEqual(self.sim.preview(acknowledged)["errors"], [])

    def test_self_loop_conflict_is_not_written(self):
        decisions = {"confirmed_mappings": [("cnm_001", 3), ("cnm_002", 3)]}
        preview = self.sim.preview(decisions)
        self.assertEqual(preview["errors"], [])
        self.assertEqual(preview["prerequisite_rows"], [])
        self.assertTrue(any("self-loop" in item["reason"] for item in preview["prerequisite_conflicts"]))
        self.sim.execute(decisions)
        self.assertEqual(len(self.sim.state["taxonomy_prerequisites"]), 0)

    def test_new_topic_requires_parent(self):
        preview = self.sim.preview(
            {"confirmed_new_topics": ["cnm_008"], "new_topic_parents": {}}
        )
        self.assertTrue(any("parent" in item for item in preview["errors"]))

    def test_standard_confidence_is_preserved(self):
        self.sim.execute(self.decisions)
        confidences = {row["confidence"] for row in self.sim.state["taxonomy_topic_standards"]}
        self.assertEqual(confidences, {"exact", "inferred"})

    def test_cycle_is_detected_and_blocked(self):
        root = self.root / "cycle"
        source_dir = fixtures.make_source(
            root,
            topics=[
                fixtures.topic("cnm_001", "甲"),
                fixtures.topic("cnm_002", "乙"),
                fixtures.topic("cnm_003", "丙"),
            ],
            dependencies=[
                {"topicId": "cnm_001", "prerequisiteId": "cnm_002", "strength": "hard", "reason": ""},
                {"topicId": "cnm_002", "prerequisiteId": "cnm_003", "strength": "hard", "reason": ""},
                {"topicId": "cnm_003", "prerequisiteId": "cnm_001", "strength": "hard", "reason": ""},
            ],
            standards_items=[],
        )
        snapshot = load_internal_snapshot(
            fixtures.make_snapshot(
                root,
                subject_name="数学",
                rows=[
                    {"internal_id": 1, "name": "数学", "parent_id": None},
                    {"internal_id": 2, "name": "数与式", "parent_id": 1},
                    {"internal_id": 3, "name": "甲", "parent_id": 2},
                    {"internal_id": 4, "name": "乙", "parent_id": 2},
                    {"internal_id": 5, "name": "丙", "parent_id": 2},
                ],
            )
        )
        mapping, _ = bm.build_mapping(source_dir, snapshot)
        simulator = sim.Stage2Simulator(snapshot, mapping, load_source(source_dir), [])
        preview = simulator.preview(
            {"confirmed_mappings": [("cnm_001", 3), ("cnm_002", 4), ("cnm_003", 5)]}
        )
        self.assertTrue(any("cycle" in item["reason"] for item in preview["prerequisite_conflicts"]))
        simulator.execute(
            {"confirmed_mappings": [("cnm_001", 3), ("cnm_002", 4), ("cnm_003", 5)]}
        )
        self.assertFalse(simulator._would_cycle(
            [(row["knowledge_point_id"], row["prerequisite_knowledge_point_id"])
             for row in simulator.state["taxonomy_prerequisites"]],
            [],
        ))


if __name__ == "__main__":
    unittest.main()
