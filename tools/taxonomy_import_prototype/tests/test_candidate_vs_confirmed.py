"""Candidate projections must never be presented as confirmed mappings."""

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


class CandidateConfirmedIsolationTests(unittest.TestCase):
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
        self.default_report = vm.analyse(self.source, self.snapshot, self.mapping)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_default_projection_has_no_confirmed_mappings(self):
        self.assertFalse(self.default_report["meta"]["confirmed_mappings_available"])
        self.assertEqual(self.default_report["standards"]["confirmed_coverage"], 0)
        confirmed = self.default_report["projections"]["confirmed"]
        self.assertEqual(confirmed["both_mapped"], 0)
        self.assertEqual(confirmed["one_mapped"], 0)
        self.assertEqual(confirmed["none_mapped"], confirmed["internal_edges"])

    def test_confirmed_projection_only_uses_confirmed_rows(self):
        mapping = copy.deepcopy(self.mapping)
        # Confirm the two rows that map cnm_003/cnm_004 to internal 6.
        for row in mapping["external_topics"]:
            if row["external_id"] in {"cnm_003", "cnm_004"}:
                for candidate in row["candidates"]:
                    candidate["review_status"] = "confirmed"
        report = vm.analyse(self.source, self.snapshot, mapping)
        self.assertTrue(report["meta"]["confirmed_mappings_available"])
        confirmed = report["projections"]["confirmed"]
        self.assertEqual(confirmed["both_mapped"], 1)
        self.assertEqual(len(confirmed["real_self_loops"]), 1)
        # Candidate projection is unchanged by the review status.
        self.assertEqual(
            len(report["projections"]["candidate"]["candidate_mapping_conflicts"]), 1
        )

    def test_standards_candidate_coverage_is_not_confirmed(self):
        standards = self.default_report["standards"]
        self.assertGreater(standards["candidate_coverage"], 0)
        self.assertEqual(standards["confirmed_coverage"], 0)
        self.assertTrue(
            any(row["coverage_status"] == "candidate_suggestion" for row in standards["rows"])
        )
        mapping = copy.deepcopy(self.mapping)
        for row in mapping["external_topics"]:
            if row["external_id"] == "cnm_001":
                for candidate in row["candidates"]:
                    candidate["review_status"] = "confirmed"
        report = vm.analyse(self.source, self.snapshot, mapping)
        self.assertEqual(report["standards"]["confirmed_coverage"], 1)


if __name__ == "__main__":
    unittest.main()
