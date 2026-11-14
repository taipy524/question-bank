"""Same inputs must produce byte-identical analysis artifacts."""

from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import build_mapping as bm  # noqa: E402
import export_internal as ei  # noqa: E402
import preview_import as pi  # noqa: E402
import validate_mapping as vm  # noqa: E402
import validate_source as vs  # noqa: E402
from common import DEFAULT_INTERNAL_DUMP, DEFAULT_SOURCE_DIR  # noqa: E402

OUTPUTS = (
    "internal_snapshot.json",
    "mapping_result.json",
    "mapping_candidates.csv",
    "03_mapping_report.md",
    "mapping_validation.json",
    "04_dependency_report.md",
    "05_standards_report.md",
    "import_preview.json",
    "06_import_preview.md",
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@unittest.skipUnless(
    DEFAULT_SOURCE_DIR.is_dir() and DEFAULT_INTERNAL_DUMP.is_file(),
    "real inputs not available",
)
class DeterminismTests(unittest.TestCase):
    def _run(self, out: Path) -> None:
        for main in (ei.main, vs.main, bm.main, vm.main, pi.main):
            args = ["--out-dir", str(out)]
            if main in (vs.main, pi.main):
                args += ["--source-dir", str(DEFAULT_SOURCE_DIR)]
            self.assertEqual(main(args), 0)

    def test_outputs_are_deterministic(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            self._run(Path(first))
            self._run(Path(second))
            for name in OUTPUTS:
                self.assertEqual(
                    _sha(Path(first) / name),
                    _sha(Path(second) / name),
                    f"{name} is not deterministic",
                )


if __name__ == "__main__":
    unittest.main()
