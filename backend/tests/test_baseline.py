import os
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

from sqlalchemy import text


def test_sqlite_pragmas_and_foreign_keys(db_engine):  # noqa: ANN001
    with db_engine.connect() as connection:
        assert connection.scalar(text("PRAGMA journal_mode")) == "wal"
        assert connection.scalar(text("PRAGMA foreign_keys")) == 1
        assert connection.scalar(text("PRAGMA busy_timeout")) == 5000
        assert connection.scalar(text("PRAGMA synchronous")) == 1
        try:
            connection.execute(
                text(
                    "INSERT INTO users "
                    "(id, organization_id, username, display_name, password_hash, active, "
                    "created_at, updated_at, version) VALUES "
                    "('u', 'missing', 'u', 'u', 'hash', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1)"
                )
            )
        except Exception as exc:
            assert "FOREIGN KEY constraint failed" in str(exc)
        else:
            raise AssertionError("Foreign key constraint did not reject an orphan user")


def test_auth_permission_csrf_and_revocation(client, seeded_db, caplog):  # noqa: ANN001
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/admin/ping").status_code == 401
    assert (
        client.post("/api/auth/login", json={"username": "admin", "password": "bad"}).status_code
        == 401
    )
    response = client.post(
        "/api/auth/login", json={"username": "admin", "password": "correct-password"}
    )
    assert response.status_code == 200
    assert "httponly" in response.headers["set-cookie"].lower()
    assert "system.admin" in response.json()["permissions"]
    assert client.get("/api/admin/ping").status_code == 200
    assert client.post("/api/auth/logout").status_code == 403
    csrf = client.cookies.get("csrf_token")
    assert csrf
    assert client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf}).status_code == 200
    assert client.get("/api/auth/me").status_code == 401
    assert "correct-password" not in caplog.text
    assert csrf not in caplog.text

    reader = client.post(
        "/api/auth/login", json={"username": "reader", "password": "correct-password"}
    )
    assert reader.status_code == 200
    assert client.get("/api/admin/ping").status_code == 403


def test_empty_database_migration(tmp_path: Path) -> None:
    path = tmp_path / "fresh.db"
    env = {**os.environ, "APP_ENV": "test", "DATABASE_PATH": str(path)}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=Path(__file__).parents[1],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT count(*) FROM organizations").fetchone()[0] == 1
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]


def test_second_writer_waits_for_short_transaction(db_engine):  # noqa: ANN001
    finished = threading.Event()
    failures: list[Exception] = []

    def second_writer() -> None:
        try:
            with db_engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO organizations "
                        "(id, name, active, created_at, updated_at, version) "
                        "VALUES ('second', 'Second', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1)"
                    )
                )
        except Exception as exc:
            failures.append(exc)
        finally:
            finished.set()

    with db_engine.connect() as first:
        first.exec_driver_sql("BEGIN IMMEDIATE")
        thread = threading.Thread(target=second_writer)
        thread.start()
        time.sleep(0.15)
        assert not finished.is_set()
        first.commit()
    thread.join(timeout=3)
    assert finished.is_set()
    assert not failures


def test_backup_and_restore_scripts(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    restored = tmp_path / "restored.db"
    output_dir = tmp_path / "backups"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE sample (value TEXT NOT NULL)")
        connection.execute("INSERT INTO sample (value) VALUES ('preserved')")
        connection.commit()

    workspace = Path(__file__).parents[2]
    backup = subprocess.run(
        [
            sys.executable,
            str(workspace / "scripts" / "backup_db.py"),
            "--database",
            str(source),
            "--output-dir",
            str(output_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert backup.returncode == 0, backup.stderr
    backup_path = next(output_dir.glob("*.sqlite3"))
    restore = subprocess.run(
        [
            sys.executable,
            str(workspace / "scripts" / "restore_db.py"),
            str(backup_path),
            "--database",
            str(restored),
            "--confirm-application-stopped",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert restore.returncode == 0, restore.stderr
    with sqlite3.connect(restored) as connection:
        assert connection.execute("SELECT value FROM sample").fetchone()[0] == "preserved"
