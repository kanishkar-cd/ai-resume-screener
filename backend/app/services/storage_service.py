import hashlib
import os
import uuid
from pathlib import Path

from fastapi import UploadFile

from app.core.exceptions import InternalServerException

DEFAULT_STORAGE_ROOT = Path(__file__).resolve().parents[3] / "storage" / "projects"


class StorageIOException(InternalServerException):
    error_code = "STORAGE_ERROR"
    default_message = "The uploaded file could not be stored."


class StorageService:
    """Secure physical storage for project-owned uploaded files."""

    def __init__(self, root: Path = DEFAULT_STORAGE_ROOT) -> None:
        self.root = root.resolve()

    def project_directory(self, project_id: uuid.UUID, subfolder: str) -> Path:
        if subfolder not in {"resumes", "job_description", "job_descriptions"}:
            raise StorageIOException("Invalid document storage directory.")
        directory = (self.root / str(project_id) / subfolder).resolve()
        if self.root not in directory.parents:
            raise StorageIOException("Invalid document storage path.")
        return directory

    async def save_file(
        self,
        file: UploadFile,
        project_id: uuid.UUID,
        subfolder: str,
        extension: str,
    ) -> tuple[str, str, int, str]:
        """Stream a file to a UUID name while calculating its SHA-256 hash."""
        directory = self.project_directory(project_id, subfolder)
        stored_filename = f"{uuid.uuid4()}{extension}"
        destination = directory / stored_filename
        digest = hashlib.sha256()
        size = 0
        try:
            directory.mkdir(parents=True, exist_ok=True)
            await file.seek(0)
            with destination.open("xb") as output:
                while chunk := await file.read(1024 * 1024):
                    output.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
            await file.seek(0)
        except OSError as exc:
            destination.unlink(missing_ok=True)
            raise StorageIOException() from exc
        return stored_filename, str(destination), size, digest.hexdigest()

    def get_file_path(
        self, stored_filename: str, project_id: uuid.UUID, subfolder: str
    ) -> Path:
        """Resolve a UUID-named document beneath its project directory."""
        if Path(stored_filename).name != stored_filename:
            raise StorageIOException("Invalid stored filename.")
        return self.project_directory(project_id, subfolder) / stored_filename

    def delete_file(self, file_path: str) -> bool:
        """Delete a stored file only when it belongs to the configured root."""
        path = Path(file_path).resolve()
        if self.root not in path.parents:
            raise StorageIOException("Refusing to delete a file outside storage.")
        try:
            if not path.exists():
                return False
            os.remove(path)
            return True
        except OSError as exc:
            raise StorageIOException() from exc

    def resolve_file(self, file_path: str) -> Path | None:
        """Resolve an existing regular file while enforcing the storage boundary."""
        path = Path(file_path).resolve()
        if self.root not in path.parents:
            raise StorageIOException("Document path is outside configured storage.")
        return path if path.is_file() else None
