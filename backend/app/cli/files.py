# ruff: noqa: E501, E702
"""Safe local attachment maintenance commands.

Usage: python -m app.cli.files verify [--sha256] [--file-id ID]
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_engine
from app.core.models import FileObject, FileReplica, utc_now
from app.modules.attachments.storage import StorageError, get_storage


def verify(args: argparse.Namespace) -> int:
    storage = get_storage()
    counts = {"ok": 0, "missing": 0, "mismatch": 0}
    with Session(get_engine()) as db:
        statement = select(FileReplica).where(
            FileReplica.storage_provider == "LOCAL", FileReplica.deleted_at.is_(None)
        )
        if args.file_id:
            statement = statement.where(FileReplica.file_object_id == args.file_id)
        for replica in db.scalars(statement):
            try:
                stat = storage.stat(replica.object_key)
                mismatch = stat.size_bytes != replica.size_bytes
                if args.sha256 and not mismatch:
                    digest = hashlib.sha256(
                        storage.open_stream(replica.object_key).read()
                    ).hexdigest()
                    mismatch = digest != replica.sha256
            except StorageError:
                mismatch = True
                counts["missing"] += 1
                if not args.dry_run:
                    db.get(FileObject, replica.file_object_id).file_status = "MISSING"
            if mismatch:
                counts["mismatch"] += 1
            else:
                counts["ok"] += 1
                if not args.dry_run:
                    replica.last_checked_at = utc_now()
        if not args.dry_run:
            db.commit()
    print(json.dumps(counts, ensure_ascii=False))
    return 1 if counts["missing"] or counts["mismatch"] else 0


def cleanup_staged(args: argparse.Namespace) -> int:
    cutoff = utc_now() - timedelta(hours=get_settings().upload_staged_ttl_hours)
    with Session(get_engine()) as db:
        records = db.scalars(
            select(FileObject).where(
                FileObject.file_status == "STAGED", FileObject.created_at < cutoff
            )
        ).all()
        if not args.dry_run:
            for item in records:
                item.file_status = "DELETED"
                item.deleted_at = utc_now()
            db.commit()
    print(json.dumps({"dry_run": args.dry_run, "staged": len(records)}, ensure_ascii=False))
    return 0


def cleanup_orphans(args: argparse.Namespace) -> int:
    storage = get_storage()
    known: set[str]
    with Session(get_engine()) as db:
        known = set(
            db.scalars(
                select(FileReplica.object_key).where(FileReplica.storage_provider == "LOCAL")
            ).all()
        )
    cutoff = utc_now().timestamp() - get_settings().file_local_retention_days * 86400
    candidates = [
        path
        for path in storage.root.rglob("*")
        if path.is_file()
        and path.stat().st_mtime < cutoff
        and path.relative_to(storage.root).as_posix() not in known
    ]
    removed = 0
    if not args.dry_run:
        for path in candidates:
            path.unlink()
            removed += 1
    print(
        json.dumps(
            {"dry_run": args.dry_run, "orphans": len(candidates), "removed": removed},
            ensure_ascii=False,
        )
    )
    return 0


def manifest(_args: argparse.Namespace) -> int:
    with Session(get_engine()) as db:
        data = [
            {
                "file_id": r.file_object_id,
                "provider": r.storage_provider,
                "object_key_digest": hashlib.sha256(r.object_key.encode()).hexdigest()[:16],
                "size_bytes": r.size_bytes,
                "sha256": r.sha256,
                "status": r.replica_status,
            }
            for r in db.scalars(select(FileReplica)).all()
        ]
    print(json.dumps(data, ensure_ascii=False))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("--sha256", action="store_true")
    verify_parser.add_argument("--file-id")
    verify_parser.add_argument("--dry-run", action="store_true")
    verify_parser.set_defaults(func=verify)
    staged = sub.add_parser("cleanup-staged")
    staged.add_argument("--dry-run", action="store_true", default=True)
    staged.add_argument("--execute", action="store_false", dest="dry_run")
    staged.set_defaults(func=cleanup_staged)
    orphan = sub.add_parser("cleanup-orphans")
    orphan.add_argument("--dry-run", action="store_true", default=True)
    orphan.add_argument("--execute", action="store_false", dest="dry_run")
    orphan.set_defaults(func=cleanup_orphans)
    export = sub.add_parser("export-manifest")
    export.set_defaults(func=manifest)
    args = parser.parse_args()
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
