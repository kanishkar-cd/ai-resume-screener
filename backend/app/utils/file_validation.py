from pathlib import Path

from fastapi import UploadFile

from app.core.constants import (
    ALLOWED_EXTENSIONS,
    ALLOWED_MIME_TYPES,
    MAX_FILE_SIZE_BYTES,
    MAX_BATCH_FILE_COUNT,
    MAX_BATCH_PAYLOAD_SIZE,
)
from app.core.exceptions import AppException

MIME_BY_EXTENSION = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
}


class InvalidFileTypeException(AppException):
    status_code = 400
    error_code = "INVALID_FILE_TYPE"
    default_message = "Only valid PDF, DOCX, and TXT files are supported."


class FileTooLargeException(AppException):
    status_code = 413
    error_code = "FILE_TOO_LARGE"
    default_message = "The uploaded file exceeds the 10 MB size limit."


class EmptyFileException(AppException):
    status_code = 400
    error_code = "EMPTY_FILE"
    default_message = "The uploaded file is empty."


class BatchFileCountException(AppException):
    status_code = 413
    error_code = "BATCH_FILE_COUNT_EXCEEDED"
    default_message = "A resume batch may contain at most 50 files."


class BatchPayloadTooLargeException(AppException):
    status_code = 413
    error_code = "BATCH_PAYLOAD_TOO_LARGE"
    default_message = "The resume batch exceeds the 100 MB aggregate limit."


def _matches_signature(extension: str, content: bytes) -> bool:
    if extension == ".pdf":
        return content.startswith(b"%PDF-")
    if extension == ".docx":
        return content.startswith(b"PK\x03\x04")
    if extension == ".txt":
        if b"\x00" in content:
            return False
        try:
            content.decode("utf-8")
        except UnicodeDecodeError:
            return False
        return True
    return False


async def validate_file(file: UploadFile) -> tuple[str, str]:
    """Validate extension, size, declared MIME, and file signature."""
    filename = Path(file.filename or "").name
    extension = Path(filename).suffix.lower()
    expected_mime = MIME_BY_EXTENSION.get(extension)
    if extension not in ALLOWED_EXTENSIONS or expected_mime is None:
        raise InvalidFileTypeException()
    if file.content_type not in ALLOWED_MIME_TYPES or file.content_type != expected_mime:
        raise InvalidFileTypeException("File MIME type does not match its extension.")

    content = await file.read(MAX_FILE_SIZE_BYTES + 1)
    await file.seek(0)
    if not content:
        raise EmptyFileException()
    if len(content) > MAX_FILE_SIZE_BYTES:
        raise FileTooLargeException()
    if not _matches_signature(extension, content[:2048]):
        raise InvalidFileTypeException("File content does not match its declared type.")
    return filename, extension


async def validate_batch(files: list[UploadFile]) -> None:
    """Validate batch count and aggregate stream size without consuming uploads."""
    if not files:
        raise EmptyFileException("At least one resume file is required.")
    if len(files) > MAX_BATCH_FILE_COUNT:
        raise BatchFileCountException()
    total_size = 0
    for file in files:
        while chunk := await file.read(1024 * 1024):
            total_size += len(chunk)
            if total_size > MAX_BATCH_PAYLOAD_SIZE:
                for reset_file in files:
                    await reset_file.seek(0)
                raise BatchPayloadTooLargeException()
        await file.seek(0)
