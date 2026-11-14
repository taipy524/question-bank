"""Real pinned-source validation (counts, cross-stage edges, standards)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common import DEFAULT_SOURCE_DIR, file_sha256, load_source  # noqa: E402
from validate_source import validate  # noqa: E402


@unittest.skipUnless(DEFAULT_SOURCE_DIR.is_dir(), "pinned source data not available")
class SourceValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.hashes_before = {
            path.name: file_sha256(path)
            for path in (DEFAULT_SOURCE_DIR / "data").glob("*.json")
        }
        cls.source = load_source(DEFAULT_SOURCE_DIR)
        cls.report = validate(DEFAULT_SOURCE_DIR)

    def test_no_errors(self):
        self.assertEqual(self.report["errors"], [])

    def test_expected_counts(self):
        counts = self.report["counts"]
        self.assertEqual(counts["junior_topics"], 315)
        self.assertEqual(counts["volumes"], {"7上": 61, "7下": 58, "8上": 57, "8下": 57, "9上": 49, "9下": 33})
        self.assertEqual(counts["junior_internal_edges"], 563)
        self.assertEqual(counts["junior_to_primary_edges"], 45)
        self.assertEqual(counts["standards_stage4_math"], 157)

    def test_strength_and_cross_stage(self):
        counts = self.report["counts"]
        self.assertEqual(counts["junior_internal_strength"], {"hard": 454, "soft": 109})
        self.assertEqual(counts["junior_to_primary_strength"], {"hard": 32, "soft": 13})

    def test_standards_references(self):
        counts = self.report["counts"]
        self.assertEqual(counts["topic_standard_refs"], 383)
        self.assertEqual(counts["topic_standard_refs_by_confidence"], {"exact": 286, "inferred": 97})
        self.assertEqual(counts["topics_without_standards"], ["cnm_130", "cnm_192"])
        self.assertEqual(len(counts["unused_stage4_standards"]), 15)

    def test_no_self_loops_duplicates_or_cycles(self):
        self.assertEqual(self.source["duplicate_ids"], [])
        keys = [(edge["topicId"], edge["prerequisiteId"]) for edge in self.source["dependencies"]]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertFalse(any(topic == prerequisite for topic, prerequisite in keys))

    def test_aliases_are_present(self):
        self.assertEqual(self.report["counts"]["aliases"], 18)

    def test_source_files_are_not_modified(self):
        hashes_after = {
            path.name: file_sha256(path)
            for path in (DEFAULT_SOURCE_DIR / "data").glob("*.json")
        }
        self.assertEqual(self.hashes_before, hashes_after)


if __name__ == "__main__":
    unittest.main()
