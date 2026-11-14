"""Post-mapping dependency/standards checks and input consistency errors."""

from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import build_mapping as bm  # noqa: E402
import fixtures  # noqa: E402
import validate_mapping as vm  # noqa: E402
from common import load_internal_snapshot  # noqa: E402


class MappingValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = fixtures.make_source(
            self.root,
            topics=fixtures.mapping_topics(),
            dependencies=fixtures.mapping_dependencies(),
            standards_items=fixtures.mapping_standards(),
        )
        self.snapshot = load_internal_snapshot(
            fixtures.make_snapshot(self.root, subject_name="数学", rows=fixtures.mapping_snapshot_rows())
        )
        self.mapping, _ = bm.build_mapping(self.source, self.snapshot)
        self.report = vm.analyse(self.source, self.snapshot, self.mapping)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_no_mapping_errors(self):
        self.assertEqual(self.report["checks"]["errors"], [])
        self.assertEqual(self.report["checks"]["external_rows"], 9)
        self.assertEqual(self.report["checks"]["missing_external"], [])

    def test_detects_candidate_mapping_conflict_not_real_self_loop(self):
        candidate = self.report["projections"]["candidate"]
        conflicts = candidate["candidate_mapping_conflicts"]
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["internal_id"], 6)
        self.assertEqual(candidate["real_self_loops"], [])
        self.assertEqual(candidate["mapped_cycles"], [])
        confirmed = self.report["projections"]["confirmed"]
        self.assertEqual(confirmed["real_self_loops"], [])

    def test_counts_add_up(self):
        deps = self.report["dependencies"]
        self.assertEqual(
            deps["both_mapped"] + deps["one_mapped"] + deps["none_mapped"],
            deps["internal_edges"],
        )
        self.assertEqual(deps["cross_stage_edges"], 1)

    def test_standards_candidate_vs_confirmed(self):
        standards = self.report["standards"]
        self.assertEqual(standards["stage4_total"], 3)
        self.assertEqual(standards["candidate_coverage"], 2)
        self.assertEqual(standards["confirmed_coverage"], 0)
        self.assertEqual(standards["without_external_topics"], ["cms-2022:4.GA.01"])

    def test_missing_external_is_an_error(self):
        broken = copy.deepcopy(self.mapping)
        broken["external_topics"] = broken["external_topics"][:-1]
        report = vm.analyse(self.source, self.snapshot, broken)
        self.assertTrue(any("missing" in item for item in report["checks"]["errors"]))

    def test_duplicate_pair_is_an_error(self):
        broken = copy.deepcopy(self.mapping)
        for row in broken["external_topics"]:
            if row["candidates"]:
                row["candidates"].append(copy.deepcopy(row["candidates"][0]))
                break
        report = vm.analyse(self.source, self.snapshot, broken)
        self.assertTrue(any("duplicate" in item for item in report["checks"]["errors"]))

    def test_duplicate_mapped_edges_are_reported(self):
        extra_source = fixtures.make_source(
            self.root,
            topics=fixtures.mapping_topics() + [fixtures.topic("cnm_010", "统计图表", domain="统计与概率")],
            dependencies=fixtures.mapping_dependencies()
            + [
                {"topicId": "cnm_010", "prerequisiteId": "cnm_006", "strength": "hard", "reason": "dup"},
                {"topicId": "cnm_005", "prerequisiteId": "cnm_006", "strength": "soft", "reason": "dup"},
            ],
            standards_items=fixtures.mapping_standards(),
        )
        mapping, _ = bm.build_mapping(extra_source, self.snapshot)
        report = vm.analyse(extra_source, self.snapshot, mapping)
        deps = report["dependencies"]
        self.assertGreaterEqual(len(deps["mapped_duplicate_edges"]), 1)
        self.assertEqual(deps["mapped_duplicate_edges"][0]["internal_topic"], 9)


if __name__ == "__main__":
    unittest.main()
