from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile


class UploadedEnvFileService:
    MAX_SIZE_BYTES = 100 * 1024

    def build_input(
        self,
        *,
        filename: str,
        content: bytes,
        content_type: str | None = None,
    ) -> dict[str, Any]:
        self.validate(filename=filename, content=content, content_type=content_type)
        return {
            "filename": Path(filename).name,
            "content": content,
            "content_type": content_type or "text/plain",
            "size": len(content),
            "source": "uploaded",
        }

    async def build_input_from_upload(self, upload: UploadFile) -> dict[str, Any] | None:
        if not upload or not upload.filename:
            return None
        content = await upload.read()
        return self.build_input(
            filename=upload.filename,
            content=content,
            content_type=upload.content_type,
        )

    def validate(
        self,
        *,
        filename: str,
        content: bytes,
        content_type: str | None = None,
    ) -> None:
        if not self._is_allowed_filename(filename):
            raise HTTPException(
                status_code=400,
                detail="Invalid environment file. Accepted names include .env, .env.*, and .txt.",
            )

        if len(content) > self.MAX_SIZE_BYTES:
            raise HTTPException(
                status_code=400,
                detail="Environment file is too large. Maximum supported size is 100 KB.",
            )

        if b"\x00" in content:
            raise HTTPException(
                status_code=400,
                detail="Environment file appears to contain binary content and was rejected.",
            )

        allowed_content_type = (
            not content_type
            or content_type.startswith("text/")
            or content_type in {"application/octet-stream", "application/x-env"}
        )
        if not allowed_content_type:
            raise HTTPException(
                status_code=400,
                detail="Unsupported environment file type. Please upload a plain text file.",
            )

    def _is_allowed_filename(self, filename: str) -> bool:
        name = Path(filename).name.lower()
        return (
            name == ".env"
            or name.startswith(".env.")
            or name.endswith(".env")
            or name.endswith(".txt")
        )
