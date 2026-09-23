#!/usr/bin/env python3
"""Verify and atomically restore a SQLite backup after the application is stopped."""

import argparse
import hashlib
import json
import os
import sqlite3
import sys
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


def expected_hash(backup_path: Path, value: str | None) -> str | None:
    if value:
        return value.lower()
    manifest_path = backup_path.with_suffix(".json")
    if manifest_path.is_file():
        return json.loads(manifest_path.read_text(encoding="utf-8"))["sha256"].lower()
    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup", type=Path, help="Verified SQLite backup file")
    parser.add_argument(
        "--database",
        default=os.environ.get("DATABASE_URL", "/var/lib/boyan/app.db"),
        help="Target SQLite path or sqlite:/// URL",
    )
    parser.add_argument("--sha256", help="Expected SHA-256 if no sidecar manifest exists")
    parser.add_argument(
        "--confirm-application-stopped",
        action="store_true",
        help="Required acknowledgement that the application service is stopped",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.confirm_application_stopped:
        raise RuntimeError("Stop the application, then pass --confirm-application-stopped")
    backup_path = args.backup.resolve()
    target_path = database_path(args.database)
    if not backup_path.is_file():
        raise FileNotFoundError(f"Backup does not exist: {backup_path}")
    expected = expected_hash(backup_path, args.sha256)
    actual = sha256(backup_path)
    if expected is None:
        raise RuntimeError("Provide --sha256 or the backup JSON manifest")
    if actual != expected:
        raise RuntimeError("Backup SHA-256 does not match the expected value")

    target_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = target_path.with_name(f".{target_path.name}.restore.tmp")
    try:
        source = sqlite3.connect(backup_path)
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
            raise RuntimeError(f"Restored database integrity check failed: {integrity}")
        os.chmod(temporary_path, 0o640)
        os.replace(temporary_path, target_path)
        print(f"Restored {backup_path.name} to {target_path}; integrity_check={integrity}")
        return 0
    finally:
        temporary_path.unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"Restore failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
