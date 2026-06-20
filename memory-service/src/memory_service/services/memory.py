from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Protocol
from urllib.parse import quote

from openai import OpenAI

from ..config import MemorySettings
from ..logger import elapsed_ms, get_logger, log_exception, log_info, start_timer
from .user_memory import UserMemoryScheduler, UserMemorySynthesizer

MEMORY_SYSTEM_PROMPT = """
你是 AICHAN 的长期记忆日志整理器。
输入是一批按时间排列的聊天记录行，通常形如 [时间] role: 内容。
你的任务不是写摘要，而是把有信息量的原始记录整理成可长期追加的 markdown 日志。
规则：
- 每条输出一行，必须以 "- " 开头；保留输入顺序。
- 每条输出都必须保留原始时间；若输入行有 [时间]，照抄这个时间，不要改写、补全或推测。
- 尽量一条输入事实对应一条输出日志，不要把多条发言合并成泛泛结论。
- 保留说话人、对象、名字、数字、约束、偏好、承诺、结论、任务进展、工具结果和仍可能复用的上下文。
- 用户或 assistant 明确说过的话要尽量保留原意和关键原文；可以压缩冗余语气词，但不能丢掉事实、条件、否定、时间和限定。
- 去掉只用于系统结构的文本，例如空行、<turn ... />、纯包装性的 <messages>/<message> 外壳、无内容的格式标记。
- 媒体、文件、表情等节点若包含 object_key、name、summary 或用户表达意图，必须保留这些信息。
- 寒暄、重复确认、无后续价值的客套可以丢弃；但只要含有偏好、需求、情绪、关系或事实，就必须记录。
- 不要编造输入中没有的信息；不输出标题、章节、解释、代码块或 JSON。
""".strip()

USER_MEMORY_EMPTY_TEMPLATE = "## 用户画像\n\n## 相关记忆\n"


@dataclass(frozen=True)
class CompressResult:
    content_markdown: str
    added_markdown: str
    added_count: int


@dataclass(frozen=True)
class UserMemoryPage:
    user_id: str
    content_markdown: str
    start_line: int
    line_count: int
    total_lines: int
    has_more: bool


class MemoryCompressor(Protocol):
    def compress(self, messages_text: str) -> str:
        pass


class OpenAiMemoryCompressor:
    def __init__(self, settings: MemorySettings) -> None:
        self._model = settings.model
        self._client = OpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            timeout=settings.llm_timeout,
            max_retries=settings.llm_max_retries,
        )

    def compress(self, messages_text: str) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            temperature=0,
            messages=[
                {"role": "system", "content": MEMORY_SYSTEM_PROMPT},
                {"role": "user", "content": messages_text},
            ],
        )
        return response.choices[0].message.content or ""


class MemoryService:
    def __init__(
        self,
        root_dir: str | Path,
        compressor: MemoryCompressor,
        session_max_lines: int = 500,
        user_memory_synthesizer: UserMemorySynthesizer | None = None,
        user_memory_scheduler: UserMemoryScheduler | None = None,
    ) -> None:
        self._logger = get_logger("memory")
        self._root_dir = Path(root_dir)
        self._compressor = compressor
        self._session_max_lines = session_max_lines
        self._user_memory_synthesizer = user_memory_synthesizer
        self._user_memory_scheduler = user_memory_scheduler
        self._root_dir.mkdir(parents=True, exist_ok=True)
        self._session_dir = self._root_dir / "sessions"
        self._user_dir = self._root_dir / "users"
        self._session_dir.mkdir(parents=True, exist_ok=True)
        self._user_dir.mkdir(parents=True, exist_ok=True)
        self._user_locks: dict[str, Lock] = {}
        self._user_locks_guard = Lock()

    def read(self, session_id: str) -> str:
        path = self._session_memory_path(session_id)
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def read_user_memory(self, user_id: str) -> str:
        path = self._user_memory_path(user_id)
        if not path.exists():
            return USER_MEMORY_EMPTY_TEMPLATE
        return path.read_text(encoding="utf-8")

    def read_user_memory_page(self, user_id: str, start_line: int, line_count: int) -> UserMemoryPage:
        if start_line < 0:
            raise ValueError("start_line must be non-negative")
        if line_count < 1:
            raise ValueError("line_count must be positive")
        content_markdown = self.read_user_memory(user_id)
        return _paginate_user_memory(
            user_id=user_id,
            content_markdown=content_markdown,
            start_line=start_line,
            line_count=line_count,
        )

    def compress_and_append(self, session_id: str, messages_text: str) -> CompressResult:
        current = self.read(session_id)
        if not messages_text.strip():
            # 空输入没有任何可提炼事实，直接成功返回；这样 agent 可以把“无可压缩内容”
            # 当作幂等边界处理，也避免为了空白文本消耗一次 LLM 调用。
            return CompressResult(content_markdown=current, added_markdown="", added_count=0)

        added_markdown = _normalize_bullets(self._compressor.compress(messages_text))
        if not added_markdown:
            return CompressResult(content_markdown=current, added_markdown="", added_count=0)

        content_markdown = _append_markdown(current=current, added=added_markdown)
        content_markdown = _truncate_session_markdown(
            content_markdown=content_markdown,
            max_lines=self._session_max_lines,
        )
        self._session_memory_path(session_id).write_text(content_markdown, encoding="utf-8")
        self._schedule_user_memory_update(messages_text=messages_text, added_markdown=added_markdown)
        return CompressResult(
            content_markdown=content_markdown,
            added_markdown=added_markdown,
            added_count=len(added_markdown.splitlines()),
        )

    def shutdown(self, timeout_seconds: float) -> None:
        if self._user_memory_scheduler is None:
            return
        self._user_memory_scheduler.shutdown(timeout_seconds=timeout_seconds)

    def _schedule_user_memory_update(self, *, messages_text: str, added_markdown: str) -> None:
        if self._user_memory_synthesizer is None or self._user_memory_scheduler is None:
            return
        user_messages = _extract_user_messages(messages_text)
        if not user_messages:
            return
        for user_id, user_messages_text in user_messages.items():
            self._user_memory_scheduler.schedule(
                lambda user_id=user_id, user_messages_text=user_messages_text: (
                    self._safe_update_user_memory(
                        user_id=user_id,
                        user_messages_text=user_messages_text,
                        added_markdown=added_markdown,
                    )
                )
            )

    def _safe_update_user_memory(
        self,
        *,
        user_id: str,
        user_messages_text: str,
        added_markdown: str,
    ) -> None:
        try:
            self._update_user_memory(
                user_id=user_id,
                user_messages_text=user_messages_text,
                added_markdown=added_markdown,
            )
        except Exception:
            log_exception(self._logger, "memory.user_memory_failed", user_id=user_id)

    def _update_user_memory(
        self,
        *,
        user_id: str,
        user_messages_text: str,
        added_markdown: str,
    ) -> None:
        lock = self._user_lock(user_id)
        started_at = start_timer()
        with lock:
            current = self.read_user_memory(user_id)
            # 用户级记忆允许提炼和去重，但归属必须严格按 user_id 分桶；
            # 因此给模型的输入同时包含该用户原始发言片段和本轮无损日志，避免群聊多人串档。
            new_logs_markdown = (
                "【该用户原始消息片段】\n"
                f"{user_messages_text.strip()}\n\n"
                "【本轮无损压缩日志】\n"
                f"{added_markdown.strip()}"
            )
            synthesized = self._user_memory_synthesizer.synthesize(current, new_logs_markdown)  # type: ignore[union-attr]
            normalized = _normalize_user_memory_markdown(synthesized)
            self._user_memory_path(user_id).write_text(normalized, encoding="utf-8")
        log_info(
            self._logger,
            "memory.user_memory_updated",
            user_id=user_id,
            elapsed_ms=elapsed_ms(started_at),
        )

    def _user_lock(self, user_id: str) -> Lock:
        with self._user_locks_guard:
            lock = self._user_locks.get(user_id)
            if lock is None:
                lock = Lock()
                self._user_locks[user_id] = lock
            return lock

    def _session_memory_path(self, session_id: str) -> Path:
        return self._session_dir / f"{_memory_filename(session_id, field_name='session_id')}.md"

    def _user_memory_path(self, user_id: str) -> Path:
        return self._user_dir / f"{_memory_filename(user_id, field_name='user_id')}.md"


def _normalize_bullets(raw: str) -> str:
    bullets: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        stripped = stripped.lstrip("-*• \t")
        if not stripped:
            continue
        bullets.append(f"- {stripped}")
    return "\n".join(bullets)


def _append_markdown(*, current: str, added: str) -> str:
    current = current.rstrip()
    added = added.strip()
    if not current:
        return f"{added}\n"
    return f"{current}\n{added}\n"


def _extract_user_messages(messages_text: str) -> dict[str, str]:
    # 日志是行格式，单行里通常保留一个原始 `<message ... user_id="...">` 片段；
    # 按行分桶可以保留该用户的上下文，同时避免把群聊里其他人的原话喂给同一个用户画像。
    user_messages: dict[str, list[str]] = {}
    for line in messages_text.splitlines():
        match = re.search(r'user_id="([^"]+)"', line)
        if match is None:
            continue
        user_id = match.group(1).strip()
        if not user_id:
            continue
        user_messages.setdefault(user_id, []).append(line)
    return {user_id: "\n".join(lines) for user_id, lines in user_messages.items()}


def _memory_filename(raw_id: str, *, field_name: str) -> str:
    normalized = raw_id.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    # 记忆文件需要能从磁盘上直接看出归属；只对路径保留字符做编码，避免 `../`
    # 这类上游异常值逃逸目标目录，同时让常见 private_123 / group_456 / QQ 数字 ID 保持可读。
    return quote(normalized, safe="")


def _normalize_user_memory_markdown(raw: str) -> str:
    text = raw.strip()
    if not text:
        return USER_MEMORY_EMPTY_TEMPLATE

    portrait_lines: list[str] = []
    related_lines: list[str] = []
    section: str | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line == "## 用户画像":
            section = "portrait"
            continue
        if line == "## 相关记忆":
            section = "related"
            continue
        normalized_line = line
        if line.startswith(("- ", "* ", "• ")):
            normalized_line = f"- {line[2:].strip()}"
        elif not line.startswith("- "):
            normalized_line = f"- {line}"
        if section == "portrait":
            portrait_lines.append(normalized_line)
        elif section == "related":
            related_lines.append(normalized_line)

    portrait_block = "\n".join(portrait_lines)
    related_block = "\n".join(related_lines)
    body = "## 用户画像"
    if portrait_block:
        body = f"{body}\n{portrait_block}"
    body = f"{body}\n\n## 相关记忆"
    if related_block:
        body = f"{body}\n{related_block}"
    return f"{body}\n"


def _paginate_user_memory(
    *,
    user_id: str,
    content_markdown: str,
    start_line: int,
    line_count: int,
) -> UserMemoryPage:
    lines = content_markdown.splitlines()
    total_lines = len(lines)
    paged_lines = lines[start_line : start_line + line_count]
    paged_markdown = "\n".join(paged_lines)
    if paged_lines:
        paged_markdown = f"{paged_markdown}\n"
    has_more = start_line + len(paged_lines) < total_lines
    return UserMemoryPage(
        user_id=user_id,
        content_markdown=paged_markdown,
        start_line=start_line,
        line_count=line_count,
        total_lines=total_lines,
        has_more=has_more,
    )


def _truncate_session_markdown(*, content_markdown: str, max_lines: int) -> str:
    lines = content_markdown.splitlines()
    if len(lines) <= max_lines:
        return content_markdown
    kept_lines = lines[-max_lines:]
    return "\n".join(kept_lines) + "\n"
