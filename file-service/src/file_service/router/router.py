from fastapi import APIRouter, HTTPException, Query, Response, status

from ..services.storage import FileNotFoundError, FileRecord, FileStorage, UnsupportedTextFileError
from .schemas import (
    FileMetadataData,
    FileMetadataResponse,
    FileStoreUrlRequest,
    FileTextData,
    FileTextResponse,
    HealthResponse,
)


def create_router(file_storage: FileStorage) -> APIRouter:
    router = APIRouter()

    @router.get("/healthz", response_model=HealthResponse)
    async def healthz() -> HealthResponse:
        return HealthResponse()

    @router.post("/api/v1/files/from-url", response_model=FileMetadataResponse)
    async def store_file_from_url(request: FileStoreUrlRequest) -> FileMetadataResponse:
        try:
            record = await file_storage.store_url(
                url=request.url,
                name=request.name,
                mime=request.mime,
                kind=request.kind,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
        return _metadata_response(record)

    @router.get("/api/v1/files/{object_key}/metadata", response_model=FileMetadataResponse)
    async def get_file_metadata(object_key: str) -> FileMetadataResponse:
        try:
            record = await file_storage.metadata(object_key)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="file not found") from exc
        return _metadata_response(record)

    @router.get("/api/v1/files/{object_key}/content")
    async def get_file_content(object_key: str) -> Response:
        try:
            record = await file_storage.metadata(object_key)
            content = await file_storage.content(object_key)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="file not found") from exc
        return Response(content=content, media_type=record.mime)

    @router.get("/api/v1/files/{object_key}/text", response_model=FileTextResponse)
    async def get_file_text(
        object_key: str,
        max_chars: int = Query(default=12000, ge=1, le=50000),
    ) -> FileTextResponse:
        try:
            text, truncated = await file_storage.text(object_key, max_chars=max_chars)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="file not found") from exc
        except UnsupportedTextFileError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="file is not text") from exc
        return FileTextResponse(ok=True, data=FileTextData(object_key=object_key, text=text, truncated=truncated))

    return router


def _metadata_response(record: FileRecord) -> FileMetadataResponse:
    return FileMetadataResponse(
        ok=True,
        data=FileMetadataData(
            object_key=record.object_key,
            name=record.name,
            mime=record.mime,
            size=record.size,
            sha256=record.sha256,
        ),
    )
