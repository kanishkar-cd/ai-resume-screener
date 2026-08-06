from io import BytesIO

import pytest
from starlette.datastructures import Headers, UploadFile

from app.utils import file_validation
from app.utils.file_validation import (
    BatchFileCountException,
    BatchPayloadTooLargeException,
    validate_batch,
)


def upload(content: bytes = b"resume") -> UploadFile:
    return UploadFile(
        BytesIO(content),
        filename="resume.txt",
        headers=Headers({"content-type": "text/plain"}),
    )


@pytest.mark.asyncio
async def test_batch_rejects_more_than_fifty_files() -> None:
    with pytest.raises(BatchFileCountException):
        await validate_batch([upload() for _ in range(51)])


@pytest.mark.asyncio
async def test_batch_rejects_aggregate_payload_limit(monkeypatch) -> None:
    monkeypatch.setattr(file_validation, "MAX_BATCH_PAYLOAD_SIZE", 5)
    files = [upload(b"abc"), upload(b"def")]
    with pytest.raises(BatchPayloadTooLargeException):
        await validate_batch(files)
    assert await files[0].read() == b"abc"


@pytest.mark.asyncio
async def test_batch_accepts_fifty_files_within_limit() -> None:
    await validate_batch([upload(b"x") for _ in range(50)])
