from io import BytesIO

import pytest
from starlette.datastructures import Headers, UploadFile

from app.core.constants import MAX_FILE_SIZE_BYTES
from app.utils.file_validation import (
    FileTooLargeException,
    InvalidFileTypeException,
    validate_file,
)


def upload(filename: str, content_type: str, content: bytes) -> UploadFile:
    return UploadFile(
        BytesIO(content),
        filename=filename,
        headers=Headers({"content-type": content_type}),
    )


@pytest.mark.asyncio
async def test_validates_pdf_docx_and_txt_signatures() -> None:
    fixtures = [
        upload("resume.pdf", "application/pdf", b"%PDF-1.7\ncontent"),
        upload(
            "resume.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            b"PK\x03\x04document",
        ),
        upload("resume.txt", "text/plain", b"plain resume text"),
    ]
    for file in fixtures:
        filename, extension = await validate_file(file)
        assert filename.endswith(extension)


@pytest.mark.asyncio
async def test_rejects_mismatched_mime_and_signature() -> None:
    with pytest.raises(InvalidFileTypeException):
        await validate_file(upload("resume.pdf", "application/pdf", b"not a pdf"))
    with pytest.raises(InvalidFileTypeException):
        await validate_file(upload("resume.exe", "application/pdf", b"%PDF-1.7"))


@pytest.mark.asyncio
async def test_rejects_file_over_ten_megabytes() -> None:
    file = upload(
        "resume.pdf",
        "application/pdf",
        b"%PDF-" + b"x" * MAX_FILE_SIZE_BYTES,
    )
    with pytest.raises(FileTooLargeException):
        await validate_file(file)
