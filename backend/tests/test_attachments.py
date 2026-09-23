# ruff: noqa: E501
from io import BytesIO

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.models import FileObject, FileReplica, StudentDocument
from app.modules.attachments.storage import LocalStorageBackend, StorageError, get_storage

PNG = b"\x89PNG\r\n\x1a\n" + b"test-image"


def login(client):  # noqa: ANN001
    assert (
        client.post(
            "/api/auth/login", json={"username": "admin", "password": "correct-password"}
        ).status_code
        == 200
    )


def csrf(client):  # noqa: ANN001
    return {"X-CSRF-Token": client.cookies.get("csrf_token")}


def category(client):  # noqa: ANN001
    response = client.post(
        "/api/document-categories",
        headers=csrf(client),
        json={
            "category_code": "ID_CARD_FRONT",
            "category_name": "身份证正面",
            "sensitivity_level": "HIGHLY_SENSITIVE",
            "allowed_types": [
                {
                    "extension": "png",
                    "mime_type": "image/png",
                    "detected_content_type": "image/png",
                    "inline_preview": True,
                }
            ],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def student(client):  # noqa: ANN001
    response = client.post(
        "/api/students", headers=csrf(client), json={"full_name": "附件测试学员"}
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def test_local_storage_rejects_unsafe_keys_and_round_trips(tmp_path):
    storage = LocalStorageBackend(str(tmp_path / "attachments"), str(tmp_path / "temp"))
    result = storage.put_stream("student-documents/2026/09/a.png", BytesIO(PNG))
    assert result.size_bytes == len(PNG)
    assert storage.open_stream(result.object_key).read() == PNG
    for value in ("../outside", "C:/outside", "student-documents\\x", "x/\x00y"):
        try:
            storage.exists(value)
        except StorageError as exc:
            assert exc.code == "STORAGE_KEY_INVALID"
        else:
            raise AssertionError(value)
    assert storage.delete(result.object_key)
    assert not storage.delete(result.object_key)


def test_oss_configuration_fails_explicitly(tmp_path):
    settings = Settings(
        storage_backend="oss",
        local_storage_root=str(tmp_path / "attachments"),
        local_temp_root=str(tmp_path / "temp"),
    )
    try:
        get_storage(settings)
    except RuntimeError as exc:
        assert "OSS后端尚未实现" in str(exc)
    else:
        raise AssertionError("oss must not silently use local storage")


def test_upload_preview_replace_and_audit(client, seeded_db, tmp_path, monkeypatch):  # noqa: ANN001
    import app.modules.attachments.router as attachment_router

    storage = LocalStorageBackend(str(tmp_path / "attachments"), str(tmp_path / "temp"))
    monkeypatch.setattr(attachment_router, "get_storage", lambda: storage)
    login(client)
    category_id = category(client)
    student_id = student(client)
    uploaded = client.post(
        f"/api/students/{student_id}/documents",
        headers=csrf(client),
        data={"category_id": category_id},
        files={"file": ("id.png", PNG, "image/png")},
    )
    assert uploaded.status_code == 201, uploaded.text
    document = uploaded.json()
    assert "object_key" not in uploaded.text
    preview = client.get(f"/api/student-documents/{document['id']}/preview")
    assert preview.status_code == 200
    assert preview.headers["cache-control"] == "private, no-store"
    assert preview.headers["x-content-type-options"] == "nosniff"
    approved = client.post(
        f"/api/student-documents/{document['id']}/approve",
        headers=csrf(client),
        json={"version": document["version"]},
    )
    assert approved.status_code == 200, approved.text
    replaced = client.post(
        f"/api/student-documents/{document['id']}/replace",
        headers=csrf(client),
        files={"file": ("id-new.png", PNG + b"2", "image/png")},
    )
    assert replaced.status_code == 201, replaced.text
    with Session(seeded_db) as db:
        old = db.get(StudentDocument, document["id"])
        new = db.get(StudentDocument, replaced.json()["id"])
        assert old.document_status == "SUPERSEDED"
        assert old.file_object_id != new.file_object_id
        replica = db.scalar(
            select(FileReplica).where(FileReplica.file_object_id == new.file_object_id)
        )
        assert replica.storage_provider == "LOCAL" and "附件测试学员" not in replica.object_key
        assert db.get(FileObject, new.file_object_id).file_status == "ACTIVE"


def test_rejects_disguised_file(client, tmp_path, monkeypatch):  # noqa: ANN001
    import app.modules.attachments.router as attachment_router

    monkeypatch.setattr(
        attachment_router,
        "get_storage",
        lambda: LocalStorageBackend(str(tmp_path / "a"), str(tmp_path / "t")),
    )
    login(client)
    category_id = category(client)
    student_id = student(client)
    response = client.post(
        f"/api/students/{student_id}/documents",
        headers=csrf(client),
        data={"category_id": category_id},
        files={"file": ("fake.pdf", b"MZ executable", "application/pdf")},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "FILE_CONTENT_MISMATCH"
