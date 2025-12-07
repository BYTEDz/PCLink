from typing import Literal
from pydantic import BaseModel

class UploadInitiatePayload(BaseModel):
    file_name: str
    destination_path: str
    file_size: int | None = None
    conflict_resolution: Literal["abort", "overwrite", "keep_both"] = "abort"


class UploadInitiateResponse(BaseModel):
    upload_id: str
    final_file_name: str | None = None


class FileConflictResponse(BaseModel):
    conflict: bool = True
    existing_file: str
    options: list[str] = ["abort", "overwrite", "keep_both"]
    suggested_name: str | None = None


class DownloadInitiatePayload(BaseModel):
    file_path: str


class DownloadInitiateResponse(BaseModel):
    download_id: str
    file_size: int
    file_name: str


class DownloadStatusResponse(BaseModel):
    download_id: str
    file_size: int
    bytes_downloaded: int
    progress_percent: float
    status: str