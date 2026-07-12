from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from ..adapters.protocol import SkillDocument

LOGGER = logging.getLogger(__name__)


class LocalSkillRepository:
    """按文件指纹热加载本地 skill；坏更新不覆盖最后一次成功快照。"""

    def __init__(self, root: Path, max_skill_bytes: int, max_snapshot_bytes: int) -> None:
        self._root = root
        self._max_skill_bytes = max_skill_bytes
        self._max_snapshot_bytes = max_snapshot_bytes
        self._fingerprint: tuple[tuple[str, int, int], ...] | None = None
        self._snapshot: tuple[SkillDocument, ...] = ()

    def resolve(self) -> list[SkillDocument]:
        paths = sorted(self._root.glob("*/SKILL.md")) if self._root.exists() else []
        fingerprint = tuple((str(path), path.stat().st_mtime_ns, path.stat().st_size) for path in paths)
        if fingerprint == self._fingerprint:
            return list(self._snapshot)
        try:
            skills = tuple(self._parse(path) for path in paths)
            self._validate(skills)
        except Exception:
            if self._fingerprint is None:
                raise
            LOGGER.exception("local skill reload failed; keeping last successful snapshot")
            return list(self._snapshot)
        self._fingerprint = fingerprint
        self._snapshot = tuple(skill for skill in skills if skill.enabled)
        return list(self._snapshot)

    def _parse(self, path: Path) -> SkillDocument:
        raw = path.read_text(encoding="utf-8")
        if not raw.startswith("---\n") or "\n---\n" not in raw[4:]:
            raise ValueError(f"skill 缺少 YAML frontmatter: {path}")
        frontmatter, content = raw[4:].split("\n---\n", 1)
        metadata: Any = yaml.safe_load(frontmatter)
        if not isinstance(metadata, dict):
            raise ValueError(f"skill frontmatter 必须是对象: {path}")
        return SkillDocument(**metadata, content=content.strip())

    def _validate(self, skills: tuple[SkillDocument, ...]) -> None:
        ids: set[str] = set()
        total = 0
        for skill in skills:
            size = len(skill.content.encode("utf-8"))
            if size > self._max_skill_bytes or skill.id in ids:
                raise ValueError(f"skill 非法或重复: {skill.id}")
            ids.add(skill.id)
            total += size
        if total > self._max_snapshot_bytes:
            raise ValueError("skill 快照总大小超限")
