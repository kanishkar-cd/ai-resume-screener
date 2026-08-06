import hashlib
from io import BytesIO
from uuid import uuid4

import pytest
from starlette.datastructures import Headers, UploadFile

from app.services.storage_service import StorageService


@pytest.mark.asyncio
async def test_storage_saves_hashes_routes_and_deletes_file(tmp_path) -> None:
    content = b"candidate resume"
    file = UploadFile(
        BytesIO(content),
        filename="resume.txt",
        headers=Headers({"content-type": "text/plain"}),
    )
    project_id = uuid4()
    storage = StorageService(tmp_path / "projects")

    stored_name, file_path, size, digest = await storage.save_file(
        file, project_id, "resumes", ".txt"
    )

    resolved = storage.get_file_path(stored_name, project_id, "resumes")
    assert resolved.read_bytes() == content
    assert str(resolved) == file_path
    assert size == len(content)
    assert digest == hashlib.sha256(content).hexdigest()
    assert storage.delete_file(file_path) is True
    assert not resolved.exists()
