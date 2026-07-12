from collections.abc import Callable

import httpx
from fastapi import APIRouter, File, Header, HTTPException, UploadFile, WebSocket, WebSocketDisconnect, status
from fastapi.responses import Response

from ..adapters.registry import AdapterRegistry
from ..services.file_client import FileServiceClient
from .schemas import FileFromUrlRequest, HealthResponse


def create_router(*, adapters: AdapterRegistry, files: FileServiceClient, ready: Callable[[], bool]) -> APIRouter:
    router = APIRouter()

    @router.get("/healthz", response_model=HealthResponse)
    async def healthz() -> HealthResponse:
        return HealthResponse(status="ok")

    @router.get("/readyz", response_model=HealthResponse)
    async def readyz() -> HealthResponse:
        if not ready():
            raise HTTPException(status_code=503, detail="core-service is not ready")
        return HealthResponse(status="ready")

    @router.websocket("/api/v2/adapters/ws")
    async def adapter_ws(websocket: WebSocket) -> None:
        if not ready():
            await websocket.close(code=1013, reason="service not ready")
            return
        token = websocket.headers.get("authorization", "").removeprefix("Bearer ").strip()
        if not adapters.token_allowed(token):
            await websocket.close(code=4401, reason="unauthorized")
            return
        try:
            await adapters.handle(websocket, token)
        except (WebSocketDisconnect, RuntimeError):
            return
        except (ValueError, PermissionError) as exc:
            await websocket.close(code=4400, reason=str(exc))

    @router.get("/api/v2/adapters")
    async def list_adapters() -> dict[str, object]:
        return {"adapters": adapters.status()}

    def require_adapter(authorization: str) -> None:
        token = authorization.removeprefix("Bearer ").strip()
        if not adapters.token_allowed(token):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")

    @router.post("/api/v2/adapter/files/from-url")
    async def store_from_url(request: FileFromUrlRequest, authorization: str = Header(default="")) -> Response:
        require_adapter(authorization)
        upstream = await files.request("POST", "/api/v1/files/from-url", json={"url": request.url, "name": request.name, "mime": request.mime_type, "kind": request.kind})
        return _proxy(upstream)

    @router.post("/api/v2/adapter/files")
    async def upload_file(upload: UploadFile = File(), authorization: str = Header(default="")) -> Response:
        require_adapter(authorization)
        content = await upload.read()
        upstream = await files.request("POST", "/api/v1/files", files={"upload": (upload.filename or "upload.bin", content, upload.content_type or "application/octet-stream")})
        return _proxy(upstream)

    @router.get("/api/v2/adapter/files/{object_key}/metadata")
    async def file_metadata(object_key: str, authorization: str = Header(default="")) -> Response:
        require_adapter(authorization)
        return _proxy(await files.request("GET", f"/api/v1/files/{object_key}/metadata"))

    @router.get("/api/v2/adapter/files/{object_key}/content")
    async def file_content(object_key: str, authorization: str = Header(default="")) -> Response:
        require_adapter(authorization)
        return _proxy(await files.request("GET", f"/api/v1/files/{object_key}/content"))

    return router


def _proxy(response: httpx.Response) -> Response:
    return Response(response.content, status_code=response.status_code, media_type=response.headers.get("content-type"))
