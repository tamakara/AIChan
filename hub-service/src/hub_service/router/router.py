from __future__ import annotations

from fastapi import APIRouter, File, Header, HTTPException, UploadFile, WebSocket, WebSocketDisconnect, status
from fastapi.responses import Response

from ..services import AdapterRegistry, FileServiceClient, SessionRegistry
from .schemas import AdapterInvokeRequest, FileFromUrlRequest, HealthResponse


def create_router(
    adapters: AdapterRegistry, sessions: SessionRegistry, files: FileServiceClient,
) -> APIRouter:
    router = APIRouter()

    @router.get("/healthz", response_model=HealthResponse)
    async def healthz() -> HealthResponse:
        return HealthResponse()

    @router.websocket("/api/v1/adapters/ws")
    async def adapter_ws(websocket: WebSocket) -> None:
        authorization = websocket.headers.get("authorization", "")
        token = authorization.removeprefix("Bearer ").strip()
        if not adapters.token_allowed(token):
            await websocket.close(code=4401, reason="unauthorized")
            return
        try:
            await adapters.handle(websocket, token)
        except (WebSocketDisconnect, RuntimeError):
            return
        except (ValueError, PermissionError) as exc:
            await websocket.close(code=4400, reason=str(exc))

    @router.get("/api/v1/adapters")
    async def list_adapters() -> dict[str, object]:
        return {"adapters": adapters.status()}

    @router.post("/api/v1/adapter/invoke")
    async def invoke(request: AdapterInvokeRequest) -> dict[str, object]:
        try:
            result = await sessions.invoke(request.session_id, request.capability, request.arguments)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {"ok": True, "result": result}

    def require_adapter(authorization: str) -> None:
        token = authorization.removeprefix("Bearer ").strip()
        if not adapters.token_allowed(token):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")

    @router.post("/api/v1/adapter/files/from-url")
    async def store_from_url(request: FileFromUrlRequest, authorization: str = Header(default="")) -> Response:
        require_adapter(authorization)
        upstream = await files.request("POST", "/api/v1/files/from-url", json={
            "url": request.url, "name": request.name, "mime": request.mime_type, "kind": request.kind,
        })
        return Response(upstream.content, status_code=upstream.status_code, media_type=upstream.headers.get("content-type"))

    @router.post("/api/v1/adapter/files")
    async def upload_file(upload: UploadFile = File(), authorization: str = Header(default="")) -> Response:
        require_adapter(authorization)
        content = await upload.read()
        upstream = await files.request("POST", "/api/v1/files", files={
            "upload": (upload.filename or "upload.bin", content, upload.content_type or "application/octet-stream")
        })
        return Response(upstream.content, status_code=upstream.status_code, media_type=upstream.headers.get("content-type"))

    @router.get("/api/v1/adapter/files/{object_key}/metadata")
    async def file_metadata(object_key: str, authorization: str = Header(default="")) -> Response:
        require_adapter(authorization)
        upstream = await files.request("GET", f"/api/v1/files/{object_key}/metadata")
        return Response(upstream.content, status_code=upstream.status_code, media_type=upstream.headers.get("content-type"))

    @router.get("/api/v1/adapter/files/{object_key}/content")
    async def file_content(object_key: str, authorization: str = Header(default="")) -> Response:
        require_adapter(authorization)
        upstream = await files.request("GET", f"/api/v1/files/{object_key}/content")
        return Response(upstream.content, status_code=upstream.status_code, media_type=upstream.headers.get("content-type"))

    return router
