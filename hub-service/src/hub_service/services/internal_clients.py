from __future__ import annotations

from typing import Any

import httpx

from .protocol import AdapterRegistration


class AgentClient:
    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=None)

    async def create_session(self, session_id: str, metadata: dict[str, Any]) -> str:
        response = await self._client.post(f"{self._base_url}/sessions", json={"session_id": session_id, "metadata": metadata})
        response.raise_for_status()
        return str(response.json()["session_id"])

    async def chat(self, session_id: str, input_xml: str) -> str:
        response = await self._client.post(f"{self._base_url}/chat", json={"session_id": session_id, "input_xml": input_xml})
        response.raise_for_status()
        return str(response.json()["output_xml"])

    async def queue(self, session_id: str, input_xml: str) -> None:
        response = await self._client.post(
            f"{self._base_url}/sessions/{session_id}/queue-message", json={"input_xml": input_xml}
        )
        response.raise_for_status()

    async def aclose(self) -> None:
        await self._client.aclose()


class SkillServiceClient:
    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=10)

    async def register(self, registration: AdapterRegistration) -> None:
        response = await self._client.put(f"{self._base_url}/api/v1/adapters/skills", json={
            "adapter_id": registration.adapter_id,
            "instance_id": registration.instance_id,
            "skills": [skill.model_dump() for skill in registration.skills],
        })
        response.raise_for_status()

    async def deactivate(self, adapter_id: str, instance_id: str) -> None:
        response = await self._client.delete(
            f"{self._base_url}/api/v1/adapters/{adapter_id}/{instance_id}/skills"
        )
        response.raise_for_status()

    async def aclose(self) -> None:
        await self._client.aclose()


class FileServiceClient:
    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=30)

    async def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        return await self._client.request(method, f"{self._base_url}{path}", **kwargs)

    async def aclose(self) -> None:
        await self._client.aclose()
