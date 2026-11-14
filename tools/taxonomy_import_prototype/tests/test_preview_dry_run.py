"""Safety checks: dry-run writes only to --out-dir; no app/DB/AI imports."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROTOTYPE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROTOTYPE))

import preview_import as pi  # noqa: E402
from common import DEFAULT_INTERNAL_DUMP, DEFAULT_SOURCE_DIR  # noqa: E402

FORBIDDEN_MODULES = ("chromadb", "openai", "sqlalchemy", "pymysql", "mysql", "app")


def _tree_hashes(root: Path) -> dict[str, str]:
    if not root.exists():
        return {}
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
        and "__pycache__" not in path.parts
        and "reports" not in path.parts
    }


class DryRunSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_preview_writes_only_inside_out_dir(self):
        # Prepare inputs with a minimal run of the real pipeline.
        import build_mapping as bm
        import export_internal as ei
        import validate_mapping as vm
        import validate_source as vs

        inputs = self.root / "inputs"
        steps = [
            (ei.main, ["--mysql-dump", str(DEFAULT_INTERNAL_DUMP)]),
            (vs.main, ["--source-dir", str(DEFAULT_SOURCE_DIR)]),
            (bm.main, []),
            (vm.main, ["--source-dir", str(DEFAULT_SOURCE_DIR)]),
        ]
        for main, extra in steps:
            self.assertEqual(main(["--out-dir", str(inputs), *extra]), 0)

        out = self.root / "out"
        prototype_hashes = _tree_hashes(PROTOTYPE)
        repo_reports = PROTOTYPE.parents[1] / "reports"
        reports_hashes = _tree_hashes(repo_reports)
        self.assertEqual(pi.main(["--mapping", str(inputs / "mapping_result.json"),
                                  "--validation", str(inputs / "mapping_validation.json"),
                                  "--source-dir", str(DEFAULT_SOURCE_DIR), "--out-dir", str(out)]), 0)
        self.assertEqual(sorted(path.name for path in out.iterdir()), ["06_import_preview.md", "import_preview.json"])
        self.assertEqual(_tree_hashes(PROTOTYPE), prototype_hashes)
        self.assertEqual(_tree_hashes(repo_reports), reports_hashes)

    def test_preview_manifest_declares_no_database_writes(self):
        import build_mapping as bm
        import export_internal as ei
        import validate_mapping as vm
        import validate_source as vs

        work = self.root / "work"
        steps = [
            (ei.main, ["--mysql-dump", str(DEFAULT_INTERNAL_DUMP)]),
            (vs.main, ["--source-dir", str(DEFAULT_SOURCE_DIR)]),
            (bm.main, []),
            (vm.main, ["--source-dir", str(DEFAULT_SOURCE_DIR)]),
        ]
        for main, extra in steps:
            self.assertEqual(main(["--out-dir", str(work), *extra]), 0)
        self.assertEqual(pi.main(["--out-dir", str(work), "--source-dir", str(DEFAULT_SOURCE_DIR)]), 0)
        payload = json.loads((work / "import_preview.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["meta"]["mode"], "dry_run")
        self.assertTrue(payload["meta"]["dry_run"])
        self.assertEqual(payload["meta"]["database_writes"], 0)

    def test_prototype_has_no_forbidden_imports(self):
        pattern = re.compile(
            r"^\s*(?:from|import)\s+(" + "|".join(re.escape(name) for name in FORBIDDEN_MODULES) + r")\b",
            re.MULTILINE,
        )
        offenders = []
        for path in sorted(PROTOTYPE.glob("*.py")):
            text = path.read_text(encoding="utf-8")
            if pattern.search(text):
                offenders.append(path.name)
        self.assertEqual(offenders, [])

    def test_runtime_does_not_load_forbidden_modules(self):
        script = (
            "import sys; sys.path.insert(0, r'%s'); "
            "import preview_import, build_mapping, validate_mapping, validate_source, export_internal, inspect_source; "
            "bad=[m for m in %r if m in sys.modules]; print(','.join(bad))"
        ) % (str(PROTOTYPE), FORBIDDEN_MODULES)
        result = subprocess.run(
            [sys.executable, "-c", script], capture_output=True, text=True, check=True
        )
        self.assertEqual(result.stdout.strip(), "")

    def test_source_and_snapshot_are_not_modified(self):
        source = DEFAULT_SOURCE_DIR / "data" / "topics.json"
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        import export_internal as ei

        self.assertEqual(ei.main(["--out-dir", str(self.root / "out")]), 0)
        after = hashlib.sha256(source.read_bytes()).hexdigest()
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
