"""Schemas for the direct-upload endpoints."""

from pydantic import BaseModel


class LocalUploadResponse(BaseModel):
    """Returned after a successful HMAC-signed PUT against the local backend."""

    key: str
    etag: str
    size_bytes: int
