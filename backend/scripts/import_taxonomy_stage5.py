#!/usr/bin/env python3
"""Stage-5 external taxonomy import CLI.

Default is preview (no database reads/writes).  Real execution is gated on an
explicit licence confirmation; the external repository licence is currently
CC BY-NC 4.0 and must be reviewed before enabling it.

Usage:
    python scripts/import_taxonomy_stage5.py --source-dir /tmp/cnm \
        --mapping reports/mapping_result.json
    python scripts/import_taxonomy_stage5.py --execute --confirm-license \
        --license-status confirmed ...
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.session import SessionLocal  # noqa: E402
from app.services import taxonomy_source_import as importer  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--mapping", type=Path, default=None)
    parser.add_argument("--source-slug", default=importer.SOURCE_SLUG)
    parser.add_argument("--repo-url", default="https://github.com/xiaoyang111222/cn-math-taxonomy")
    parser.add_argument("--commit", required=True)
    parser.add_argument("--license-status", default="unconfirmed")
    parser.add_argument("--license-note", default="")
    parser.add_argument("--data-version", default=None)
    parser.add_argument("--content-hash", default=None)
    parser.add_argument(
        "--include-cross-stage",
        action="store_true",
        help="also import primary-to-junior prerequisite edges (disabled by default)",
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-license", action="store_true")
    parser.add_argument("--rollback-batch", type=int, default=None)
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="pilot slice: import only the first N junior topics (preview/execute, non-strict counts)",
    )
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> int:
    dataset = importer.load_dataset(
        args.source_dir,
        args.mapping,
        include_cross_stage=args.include_cross_stage,
    )
    mapping = dataset.get("mapping")
    strict_counts = True
    if args.limit is not None:
        dataset, mapping = importer.subset_dataset(dataset, args.limit, mapping)
        strict_counts = False
    source_meta = {
        "repo_url": args.repo_url,
        "commit_sha": args.commit,
        "data_version": args.data_version,
        "license_status": args.license_status,
        "license_note": args.license_note,
        "content_hash": args.content_hash,
    }

    if args.rollback_batch is not None:
        if not args.execute:
            print("ERROR: --rollback-batch requires --execute", file=sys.stderr)
            return 2
        async with SessionLocal() as db:
            result = await importer.rollback_source_batch(db, batch_id=args.rollback_batch)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if not args.execute:
        preview = await importer.preview_import(
            None,
            dataset,
            source_slug=args.source_slug,
            commit_sha=args.commit,
            mapping=mapping,
            strict_counts=strict_counts,
        )
        print(json.dumps({"mode": "preview", "database_writes": 0, **preview}, ensure_ascii=False, indent=2))
        return 1 if preview["validation"]["errors"] else 0

    if not args.confirm_license or args.license_status != "confirmed":
        print(
            "ERROR: real data import is blocked pending licence confirmation.\n"
            "Pass --confirm-license and --license-status confirmed only after reviewing\n"
            "the external repository licence (currently CC BY-NC 4.0) and its use scope.",
            file=sys.stderr,
        )
        return 3

    async with SessionLocal() as db:
        result = await importer.import_dataset(
            db,
            dataset,
            source_slug=args.source_slug,
            source_meta=source_meta,
            mapping=mapping,
            mode="apply",
            strict_counts=strict_counts,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run(_parse_args())))
