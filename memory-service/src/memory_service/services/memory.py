from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from openai import OpenAI

from ..config import MemorySettings

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


@dataclass(frozen=True)
class CompressResult:
    content_markdown: str
    added_markdown: str
    added_count: int


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
    def __init__(self, root_dir: str | Path, compressor: MemoryCompressor) -> None:
        self._root_dir = Path(root_dir)
        self._compressor = compressor
        self._root_dir.mkdir(parents=True, exist_ok=True)

    def read(self, session_id: str) -> str:
        path = self._memory_path(session_id)
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

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
        self._memory_path(session_id).write_text(content_markdown, encoding="utf-8")
        return CompressResult(
            content_markdown=content_markdown,
            added_markdown=added_markdown,
            added_count=len(added_markdown.splitlines()),
        )

    def _memory_path(self, session_id: str) -> Path:
        # session_id 来自外部服务，不能直接作为路径使用；hash 文件名既隔离会话，
        # 又彻底切断 ../、分隔符和平台保留字符造成的路径逃逸风险。
        digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
        return self._root_dir / f"{digest}.md"


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

