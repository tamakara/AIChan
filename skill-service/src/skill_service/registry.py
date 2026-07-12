from __future__ import annotations

from pathlib import Path
from threading import Lock
from typing import Any

import yaml

from .schemas import AdapterSkillSnapshot, SkillDocument


class SkillRegistry:
    """集中保存 skill 快照；适配器断线后停止注入，避免提示能力与真实连接漂移。"""

    def __init__(self, system_root: Path, max_skill_bytes: int, max_snapshot_bytes: int) -> None:
        self._system_root = system_root
        self._max_skill_bytes = max_skill_bytes
        self._max_snapshot_bytes = max_snapshot_bytes
        self._system_skills = self._load_system_skills()
        self._adapter_skills: dict[tuple[str, str], list[SkillDocument]] = {}
        self._lock = Lock()

    def replace_adapter(self, snapshot: AdapterSkillSnapshot) -> None:
        self._validate_snapshot(snapshot.skills)
        with self._lock:
            self._adapter_skills[(snapshot.adapter_id, snapshot.instance_id)] = list(snapshot.skills)

    def deactivate_adapter(self, adapter_id: str, instance_id: str) -> None:
        with self._lock:
            self._adapter_skills.pop((adapter_id, instance_id), None)

    def resolve(self, adapter_id: str, instance_id: str) -> list[SkillDocument]:
        with self._lock:
            adapter = list(self._adapter_skills.get((adapter_id, instance_id), []))
        return [skill for skill in [*self._system_skills, *adapter] if skill.enabled]

    def _load_system_skills(self) -> list[SkillDocument]:
        if not self._system_root.exists():
            return []
        skills = [self._parse_skill(path) for path in sorted(self._system_root.glob("*/SKILL.md"))]
        self._validate_snapshot(skills)
        return skills

    def _parse_skill(self, path: Path) -> SkillDocument:
        raw = path.read_text(encoding="utf-8")
        if not raw.startswith("---\n") or "\n---\n" not in raw[4:]:
            raise ValueError(f"skill 缺少 YAML frontmatter: {path}")
        frontmatter, content = raw[4:].split("\n---\n", 1)
        metadata: Any = yaml.safe_load(frontmatter)
        if not isinstance(metadata, dict):
            raise ValueError(f"skill frontmatter 必须是对象: {path}")
        return SkillDocument(**metadata, content=content.strip())

    def _validate_snapshot(self, skills: list[SkillDocument]) -> None:
        ids: set[str] = set()
        total = 0
        for skill in skills:
            size = len(skill.content.encode("utf-8"))
            if size > self._max_skill_bytes:
                raise ValueError(f"skill 内容过大: {skill.id}")
            if skill.id in ids:
                raise ValueError(f"skill id 重复: {skill.id}")
            ids.add(skill.id)
            total += size
        if total > self._max_snapshot_bytes:
            raise ValueError("skill 快照总大小超限")
