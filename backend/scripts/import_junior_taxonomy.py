#!/usr/bin/env python3
"""Import the junior-high math taxonomy package into QuestionBank.

Default mode is a read-only preview.  Real writes require ``--apply`` and must
target an isolated test database (database name contains ``test`` or ``e2e``)
unless ``--allow-non-test`` is passed explicitly.

Examples::

    python scripts/import_junior_taxonomy.py --package-dir ../data/cn-math-taxonomy/cf73951
    python scripts/import_junior_taxonomy.py --package-dir ../data/cn-math-taxonomy/cf73951 --apply
    python scripts/import_junior_taxonomy.py --rollback-batch 3
    python scripts/import_junior_taxonomy.py --purge-legacy
    python scripts/import_junior_taxonomy.py --purge-legacy --purge-apply \
        --legacy-max-kp-id 62 --legacy-max-question-id 77
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.engine import make_url  # noqa: E402

from app.core.config import get_db_url, settings  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.services import junior_taxonomy_service as service  # noqa: E402
from app.services import taxonomy_source_import  # noqa: E402

DEFAULT_PACKAGE = Path(__file__).resolve().parent.parent.parent / "data" / "cn-math-taxonomy" / "cf73951"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-dir", type=Path, default=DEFAULT_PACKAGE)
    parser.add_argument("--subject-id", type=int, default=1)
    parser.add_argument("--subject-name", default="初中数学")
    parser.add_argument("--commit", default=service.SOURCE_COMMIT)
    parser.add_argument("--repo-url", default=service.SOURCE_REPO)
    parser.add_argument("--apply", action="store_true", help="write to the database")
    parser.add_argument("--rollback-batch", type=int, default=None)
    parser.add_argument("--purge-legacy", action="store_true")
    parser.add_argument("--purge-apply", action="store_true")
    parser.add_argument("--legacy-max-kp-id", type=int, default=None)
    parser.add_argument("--legacy-max-question-id", type=int, default=None)
    parser.add_argument("--allow-non-test", action="store_true")
    parser.add_argument("--note", default="junior taxonomy import")
    return parser.parse_args()


def _db_name() -> str:
    url = make_url(get_db_url() or settings.DB_URL)
    return url.database or ""


def _guard(args: argparse.Namespace) -> None:
    if args.allow_non_test:
        return
    name = _db_name().lower()
    if "test" not in name and "e2e" not in name:
        raise SystemExit(
            f"REFUSED: database '{_db_name()}' does not look like a test database. "
            "Pass --allow-non-test only after explicit approval."
        )


async def _run(args: argparse.Namespace) -> int:
    package = args.package_dir.resolve()
    dataset = taxonomy_source_import.load_dataset(package, include_cross_stage=False)

    if args.rollback_batch is not None:
        _guard(args)
        async with SessionLocal() as db:
            result = await service.rollback_batch(db, args.rollback_batch)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.purge_legacy:
        _guard(args)
        async with SessionLocal() as db:
            result = await service.purge_legacy(
                db,
                subject_id=args.subject_id,
                subject_name=args.subject_name,
                legacy_max_kp_id=args.legacy_max_kp_id,
                legacy_max_question_id=args.legacy_max_question_id,
                dry_run=not args.purge_apply,
            )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if not args.apply:
        result = await service.import_package(
            db=None,  # type: ignore[arg-type]
            dataset=dataset,
            package_dir=package,
            subject_id=args.subject_id,
            subject_name=args.subject_name,
            commit=args.commit,
            repo_url=args.repo_url,
            dry_run=True,
            note=args.note,
        )
        result["manifest"] = service.manifest_summary(package).get("counts")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    _guard(args)
    async with SessionLocal() as db:
        result = await service.import_package(
            db,
            dataset,
            package_dir=package,
            subject_id=args.subject_id,
            subject_name=args.subject_name,
            commit=args.commit,
            repo_url=args.repo_url,
            dry_run=False,
            note=args.note,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run(_parse_args())))
