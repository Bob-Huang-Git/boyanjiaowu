#!/usr/bin/env python3
"""Create a consistent SQLite backup without copying a live database file."""

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def database_path(value: str) -> Path:
    if value.startswith("sqlite:///"):
        value = value[len("sqlite:///") :]
    path = Path(value)
    if not path.is_absolute():
        path = path.resolve()
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        default=os.environ.get("DATABASE_URL", "/var/lib/boyan/app.db"),
        help="SQLite path or sqlite:/// URL",
    )
    parser.add_argument(
        "--output-dir",
        default=os.environ.get("BACKUP_LOCAL_DIR", "/var/lib/boyan/backups"),
        help="Directory for local backup files",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_path = database_path(args.database)
    output_dir = Path(args.output_dir).resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"Database does not exist: {source_path}")
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target_path = output_dir / f"app-{timestamp}.sqlite3"
    temporary_path = output_dir / f".{target_path.name}.tmp"

    try:
        source = sqlite3.connect(source_path)
        target = sqlite3.connect(temporary_path)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        target = sqlite3.connect(temporary_path)
        try:
            integrity = target.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            target.close()
        if integrity != "ok":
            raise RuntimeError(f"Backup integrity check failed: {integrity}")
        os.replace(temporary_path, target_path)
        manifest = {
            "created_at": datetime.now(UTC).isoformat(),
            "database": str(source_path),
            "filename": target_path.name,
            "size_bytes": target_path.stat().st_size,
            "sha256": sha256(target_path),
            "integrity_check": integrity,
        }
        manifest_path = target_path.with_suffix(".json")
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(manifest, ensure_ascii=False))
        return 0
    finally:
        temporary_path.unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"Backup failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
