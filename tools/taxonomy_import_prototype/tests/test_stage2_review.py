"""Stage-2 review state machine and new-topic queue tests."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import build_mapping as bm  # noqa: E402
import fixtures  # noqa: E402
import stage2_review as review  # noqa: E402
from common import DEFAULT_SOURCE_DIR, load_internal_snapshot  # noqa: E402


class ReviewStateMachineTests(unittest.TestCase):
    def test_high_risk_requires_explicit_ack(self):
        store = review.ReviewStore()
        store.start(entity_type="mapping", external_id="cnm_093", internal_id=10, high_risk=True)
        with self.assertRaises(review.ReviewError):
            store.apply(
                entity_type="mapping", external_id="cnm_093", internal_id=10,
                action="confirm", reviewer="tester",
            )
        with self.assertRaises(review.ReviewError):
            store.apply(
                entity_type="mapping", external_id="cnm_093", internal_id=10,
                action="confirm", reviewer="tester", acknowledge_high_risk=True,
            )
        record = store.apply(
            entity_type="mapping", external_id="cnm_093", internal_id=10,
            action="confirm", reviewer="tester", comment="reviewed manually",
            acknowledge_high_risk=True,
        )
        self.assertEqual(record["status"], "confirmed")
        self.assertEqual(len(record["history"]), 2)

    def test_high_risk_pair_constant(self):
        self.assertEqual(
            review.HIGH_RISK_PAIRS,
            {("cnm_093", 10), ("cnm_200", 19), ("cnm_208", 10)},
        )

    def test_reject_is_kept_and_can_be_reopened(self):
        store = review.ReviewStore()
        store.start(entity_type="mapping", external_id="cnm_001", internal_id=3)
        store.apply(
            entity_type="mapping", external_id="cnm_001", internal_id=3,
            action="reject", reviewer="tester", comment="wrong",
        )
        self.assertIn(("cnm_001", 3), store.rejected_pairs())
        store.apply(
            entity_type="mapping", external_id="cnm_001", internal_id=3,
            action="reopen", reviewer="tester", comment="recheck",
        )
        self.assertNotIn(("cnm_001", 3), store.rejected_pairs())
        self.assertEqual(len(store.history), 2)

    def test_split_and_merge_do_not_touch_internal_data(self):
        store = review.ReviewStore()
        store.start(entity_type="mapping", external_id="cnm_001", internal_id=3)
        split = store.apply(
            entity_type="mapping", external_id="cnm_001", internal_id=3,
            action="split", reviewer="tester", comment="needs split",
        )
        self.assertEqual(split["status"], "needs_split")
        self.assertNotIn(("cnm_001", 3), store.confirmed_pairs())
        undo = store.apply(
            entity_type="mapping", external_id="cnm_001", internal_id=3,
            action="undo", reviewer="tester", comment="back",
        )
        self.assertEqual(undo["status"], "pending_review")

    def test_invalid_transition(self):
        store = review.ReviewStore()
        store.start(entity_type="mapping", external_id="cnm_001", internal_id=3)
        with self.assertRaises(review.ReviewError):
            store.apply(
                entity_type="mapping", external_id="cnm_001", internal_id=3,
                action="undo", reviewer="tester",
            )


@unittest.skipUnless(DEFAULT_SOURCE_DIR.is_dir(), "pinned source not available")
class RealReviewQueueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import json

        root = Path(tempfile.mkdtemp(prefix="stage2-review-"))
        cls.root = root
        # Reuse the committed stage-1 outputs.
        reports = Path(__file__).resolve().parents[3] / "reports"
        cls.mapping = json.loads((reports / "mapping_result.json").read_text(encoding="utf-8"))
        cls.snapshot = load_internal_snapshot(reports / "internal_snapshot.json")
        cls.store = review.build_review_store(cls.mapping)
        cls.queue = review.build_new_topic_queue(cls.mapping, cls.snapshot, DEFAULT_SOURCE_DIR)

    def test_queue_has_303_nodes(self):
        self.assertEqual(len(self.queue), 303)
        self.assertTrue(all(item["review_status"] == "new_topic_pending" for item in self.queue))

    def test_all_records_pending(self):
        counts = self.store.status_counts()
        self.assertEqual(counts, {"new_topic_pending": 303, "pending_review": 12})

    def test_high_risk_candidates_flagged(self):
        flagged = {
            (record["external_id"], record["internal_id"])
            for record in self.store.records.values()
            if record["high_risk"]
        }
        self.assertEqual(flagged, review.HIGH_RISK_PAIRS)

    def test_new_topic_queue_has_duplicate_checks(self):
        self.assertTrue(all("duplicate_checks" in item for item in self.queue))
        self.assertTrue(any(item["duplicate_risk"] != "none" for item in self.queue))


if __name__ == "__main__":
    unittest.main()
