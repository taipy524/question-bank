"""Explicit detection tests for duplicate ids, missing refs, self-loops and cycles."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fixtures  # noqa: E402
from validate_source import validate  # noqa: E402


def _base_topics():
    return [
        fixtures.topic("cnm_001", "甲", standards=[{"id": "cms-2022:4.NA.01", "confidence": "exact"}]),
        fixtures.topic("cnm_002", "乙"),
    ]


class ValidationErrorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _run(self, *, topics, dependencies, standards=None, aliases=None):
        source = fixtures.make_source(
            self.root,
            topics=topics,
            dependencies=dependencies,
            standards_items=standards if standards is not None else fixtures.mapping_standards(),
            aliases=aliases,
        )
        return validate(source)

    def test_duplicate_topic_id(self):
        topics = _base_topics() + [fixtures.topic("cnm_001", "重复")]
        report = self._run(topics=topics, dependencies=[])
        self.assertTrue(any("duplicate topic ids" in item for item in report["errors"]))

    def test_missing_dependency_endpoint(self):
        deps = [{"topicId": "cnm_001", "prerequisiteId": "cnm_missing", "strength": "hard", "reason": ""}]
        report = self._run(topics=_base_topics(), dependencies=deps)
        self.assertTrue(any("endpoints are not topics or aliases" in item for item in report["errors"]))

    def test_self_loop_dependency(self):
        deps = [{"topicId": "cnm_001", "prerequisiteId": "cnm_001", "strength": "hard", "reason": ""}]
        report = self._run(topics=_base_topics(), dependencies=deps)
        self.assertTrue(any("self-loop" in item for item in report["errors"]))

    def test_dependency_cycle(self):
        deps = [
            {"topicId": "cnm_001", "prerequisiteId": "cnm_002", "strength": "hard", "reason": ""},
            {"topicId": "cnm_002", "prerequisiteId": "cnm_001", "strength": "hard", "reason": ""},
        ]
        report = self._run(topics=_base_topics(), dependencies=deps)
        self.assertTrue(any("cycles" in item for item in report["errors"]))

    def test_missing_standard_reference(self):
        topics = _base_topics()
        topics[0]["standards"] = [{"id": "cms-2022:4.NA.99", "confidence": "exact"}]
        report = self._run(topics=topics, dependencies=[])
        self.assertTrue(any("standards references missing" in item for item in report["errors"]))

    def test_alias_target_missing(self):
        aliases = {"cnm_ext_999": {"name": "旧节点", "targets": ["cnm_missing"]}}
        report = self._run(topics=_base_topics(), dependencies=[], aliases=aliases)
        self.assertTrue(any("alias" in item and "missing" in item for item in report["errors"]))


if __name__ == "__main__":
    unittest.main()
