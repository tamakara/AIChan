from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Protocol

from openai import OpenAI

from ..config import MemorySettings

USER_MEMORY_SYSTEM_PROMPT = """
你是 AICHAN 的用户记忆内化整理器。
输入分两部分：当前用户记忆 markdown，以及本轮新增的无损会话日志 markdown。
你的任务是把新日志内化进用户级记忆，并按固定分类输出完整 markdown。
输出规则：
- 只输出 markdown，且必须只包含下面两个一级分类，顺序固定：
  ## 用户画像
  ## 相关记忆
- `用户画像` 记录稳定偏好、表达风格、身份背景、长期约束、关系、习惯、审美、常用工作方式。
- `相关记忆` 记录近期任务、项目上下文、承诺、待办、阶段结论、仍会复用的重要事实。
- 只保留对未来有复用价值的信息；寒暄、空泛客套、纯结构文本不要保留。
- 不能编造输入里没有的信息；若旧内容与新内容冲突，以新内容为准，并移除过时表述。
- 尽量去重合并，保持简洁，但不能丢掉关键限定、否定、时间和对象。
- 每条记忆都必须使用 `- ` markdown bullet。
- 若某个分类暂时没有内容，只保留标题，不要编造 bullet。
""".strip()


class UserMemorySynthesizer(Protocol):
    def synthesize(self, current_markdown: str, new_logs_markdown: str) -> str:
        pass


class OpenAiUserMemorySynthesizer:
    def __init__(self, settings: MemorySettings) -> None:
        self._model = settings.model
        self._client = OpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            timeout=settings.llm_timeout,
            max_retries=settings.llm_max_retries,
        )

    def synthesize(self, current_markdown: str, new_logs_markdown: str) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            temperature=0,
            messages=[
                {"role": "system", "content": USER_MEMORY_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "【当前用户记忆】\n"
                        f"{current_markdown.strip() or '(空)'}\n\n"
                        "【本轮新增无损日志】\n"
                        f"{new_logs_markdown.strip()}"
                    ),
                },
            ],
        )
        return response.choices[0].message.content or ""


class UserMemoryScheduler(Protocol):
    def schedule(self, job: Callable[[], None]) -> bool:
        pass

    def shutdown(self, timeout_seconds: float) -> None:
        pass


class ThreadedUserMemoryScheduler:
    def __init__(self, *, max_workers: int = 1) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="user-memory",
        )

    def schedule(self, job: Callable[[], None]) -> bool:
        self._executor.submit(job)
        return True

    def shutdown(self, timeout_seconds: float) -> None:
        # 用户画像提炼属于附加收益，不值得在服务关停时无限等待。
        self._executor.shutdown(wait=False, cancel_futures=True)
