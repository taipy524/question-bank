"""End-to-end run of the prototype against the pinned real inputs."""

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
from common import DEFAULT_INTERNAL_DUMP, DEFAULT_SOURCE_DIR  # noqa: E402


@unittest.skipUnless(
    DEFAULT_SOURCE_DIR.is_dir() and DEFAULT_INTERNAL_DUMP.is_file(),
    "real inputs not available",
)
class RealPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name)
        args = ["--out-dir", str(cls.out)]
        steps = [
            (ei.main, args + ["--mysql-dump", str(DEFAULT_INTERNAL_DUMP)]),
            (ins.main, args + ["--source-dir", str(DEFAULT_SOURCE_DIR)]),
            (vs.main, args + ["--source-dir", str(DEFAULT_SOURCE_DIR)]),
            (bm.main, args + ["--source-dir", str(DEFAULT_SOURCE_DIR)]),
            (vm.main, args + ["--source-dir", str(DEFAULT_SOURCE_DIR)]),
            (pi.main, args + ["--source-dir", str(DEFAULT_SOURCE_DIR)]),
        ]
        for main, main_args in steps:
            code = main(main_args)
            assert code == 0, (main, code)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def _load(self, name: str):
        return json.loads((self.out / name).read_text(encoding="utf-8"))

    def test_all_deliverables_are_generated(self):
        for name in (
            "internal_snapshot.json",
            "source_inspection.json",
            "source_validation.json",
            "02_source_data_audit.md",
            "mapping_result.json",
            "mapping_candidates.csv",
            "03_mapping_report.md",
            "mapping_validation.json",
            "04_dependency_report.md",
            "05_standards_report.md",
            "import_preview.json",
            "06_import_preview.md",
        ):
            self.assertTrue((self.out / name).is_file(), name)

    def test_mapping_covers_every_external_topic(self):
        mapping = self._load("mapping_result.json")
        ids = [row["external_id"] for row in mapping["external_topics"]]
        self.assertEqual(len(ids), 315)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(row["review_status"] == "pending_review" for row in mapping["external_topics"]))
        self.assertEqual(mapping["stats"]["external_total"], 315)
        self.assertEqual(
            mapping["stats"]["external_with_candidates"] + mapping["stats"]["external_new_topic"],
            315,
        )
        self.assertEqual(mapping["stats"]["pairs_total"], 12)
        self.assertEqual(mapping["stats"]["candidate_nodes"], 12)
        self.assertEqual(mapping["stats"]["candidate_pairs"], 12)
        self.assertEqual(mapping["stats"]["no_candidate_nodes"], 303)
        self.assertEqual(mapping["stats"]["high_risk_pairs"], 3)
        self.assertEqual(mapping["stats"]["high_risk_nodes"], 3)
        self.assertEqual(mapping["stats"]["suggestion_nodes"], 9)
        self.assertEqual(mapping["stats"]["split_candidates"], 0)
        self.assertEqual(mapping["stats"]["confirmed_pairs"], 0)

    def test_mapping_validation_has_no_errors(self):
        validation = self._load("mapping_validation.json")
        self.assertEqual(validation["checks"]["errors"], [])
        deps = validation["dependencies"]
        self.assertEqual(deps["internal_edges"], 563)
        self.assertEqual(deps["cross_stage_edges"], 45)
        self.assertEqual(deps["both_mapped"] + deps["one_mapped"] + deps["none_mapped"], 563)

    def test_preview_is_dry_run(self):
        preview = self._load("import_preview.json")
        self.assertTrue(preview["meta"]["dry_run"])
        self.assertEqual(preview["meta"]["database_writes"], 0)
        self.assertEqual(preview["summary"]["external_total"], 315)
        self.assertEqual(preview["summary"]["direct_suggestions"], 8)
        self.assertEqual(preview["summary"]["high_risk_nodes"], 3)
        self.assertEqual(preview["summary"]["confirmed_mappings"], 0)

    def test_high_risk_pairs_are_the_expected_ones(self):
        mapping = self._load("mapping_result.json")
        pairs = {
            (pair["external_id"], pair["internal_id"]): pair["risk"]
            for pair in mapping["high_risk_candidates"]
        }
        self.assertEqual(
            set(pairs),
            {("cnm_093", 10), ("cnm_200", 19), ("cnm_208", 10)},
        )
        self.assertIn("三->二", pairs[("cnm_093", 10)])
        self.assertIn("正->反", pairs[("cnm_200", 19)])
        self.assertEqual(pairs[("cnm_208", 10)], "composite_topic_contains_other_concept")

    def test_candidate_and_confirmed_projections_are_separate(self):
        validation = self._load("mapping_validation.json")
        self.assertEqual(validation["meta"]["projection_basis"], "candidate_projection")
        self.assertFalse(validation["meta"]["confirmed_mappings_available"])
        candidate = validation["projections"]["candidate"]
        safe = validation["projections"]["candidate_excluding_high_risk"]
        confirmed = validation["projections"]["confirmed"]
        self.assertEqual(len(candidate["candidate_mapping_conflicts"]), 1)
        self.assertEqual(safe["candidate_mapping_conflicts"], [])
        self.assertEqual(confirmed["both_mapped"], 0)
        self.assertEqual(confirmed["real_self_loops"], [])
        self.assertEqual(validation["standards"]["candidate_coverage"], 12)
        self.assertEqual(validation["standards"]["suggestion_coverage"], 9)
        self.assertEqual(validation["standards"]["confirmed_coverage"], 0)


if __name__ == "__main__":
    unittest.main()
