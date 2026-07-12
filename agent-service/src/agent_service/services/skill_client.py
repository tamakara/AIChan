from __future__ import annotations

from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class RuntimeSkill:
    id: str
    version: str
    content: str


class SkillClient:
    def __init__(self, base_url: str, timeout: float) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def resolve(self, adapter_id: str, instance_id: str) -> list[RuntimeSkill]:
        response = httpx.post(
            f"{self._base_url}/api/v1/skills/resolve",
            json={"adapter_id": adapter_id, "instance_id": instance_id},
            timeout=self._timeout,
        )
        response.raise_for_status()
        payload = response.json()
        skills = payload.get("skills")
        if not isinstance(skills, list):
            raise ValueError("skill-service 返回了非法响应")
        return [
            RuntimeSkill(id=str(item["id"]), version=str(item["version"]), content=str(item["content"]))
            for item in skills if isinstance(item, dict)
        ]
