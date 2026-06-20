from pathlib import Path
from typing import Callable

import pytest

from memory_service.services.memory import USER_MEMORY_EMPTY_TEMPLATE, MemoryService


class StubCompressor:
    def __init__(self, outputs: list[str] | None = None, fail: bool = False) -> None:
        self.outputs = outputs or ["- 用户喜欢高密度结论"]
        self.fail = fail
        self.calls: list[str] = []

    def compress(self, messages_text: str) -> str:
        self.calls.append(messages_text)
        if self.fail:
            raise RuntimeError("llm failed")
        return self.outputs.pop(0)


class StubUserMemorySynthesizer:
    def __init__(self, outputs: list[str] | None = None, fail: bool = False) -> None:
        self.outputs = outputs or ["## 用户画像\n- 用户喜欢中文注释\n\n## 相关记忆\n- 正在重构 memory"]
        self.fail = fail
        self.calls: list[tuple[str, str]] = []

    def synthesize(self, current_markdown: str, new_logs_markdown: str) -> str:
        self.calls.append((current_markdown, new_logs_markdown))
        if self.fail:
            raise RuntimeError("user memory failed")
        return self.outputs.pop(0)


class InlineScheduler:
    def __init__(self) -> None:
        self.jobs: list[Callable[[], None]] = []
        self.shutdown_calls: list[float] = []

    def schedule(self, job: Callable[[], None]) -> bool:
        self.jobs.append(job)
        return True

    def run_all(self) -> None:
        jobs = list(self.jobs)
        self.jobs.clear()
        for job in jobs:
            job()

    def shutdown(self, timeout_seconds: float) -> None:
        self.shutdown_calls.append(timeout_seconds)


def test_read_missing_session_returns_empty(tmp_path: Path) -> None:
    service = MemoryService(root_dir=tmp_path, compressor=StubCompressor())

    assert service.read("private_1") == ""


def test_compress_creates_markdown_file_and_appends_bullets(tmp_path: Path) -> None:
    compressor = StubCompressor(outputs=["- 用户喜欢中文注释\n已确认使用 V1"])
    service = MemoryService(root_dir=tmp_path, compressor=compressor)

    result = service.compress_and_append("private_1", "user: hello")

    assert result.added_markdown == "- 用户喜欢中文注释\n- 已确认使用 V1"
    assert result.added_count == 2
    assert result.content_markdown == "- 用户喜欢中文注释\n- 已确认使用 V1\n"
    assert compressor.calls == ["user: hello"]
    assert (tmp_path / "sessions" / "private_1.md").read_text(encoding="utf-8") == result.content_markdown
    assert list(tmp_path.glob("*.md")) == []


def test_consecutive_compress_appends_instead_of_overwriting(tmp_path: Path) -> None:
    compressor = StubCompressor(outputs=["- 第一条", "- 第二条"])
    service = MemoryService(root_dir=tmp_path, compressor=compressor)

    service.compress_and_append("private_1", "first")
    result = service.compress_and_append("private_1", "second")

    assert result.content_markdown == "- 第一条\n- 第二条\n"


def test_different_sessions_are_isolated_by_readable_files(tmp_path: Path) -> None:
    compressor = StubCompressor(outputs=["- A", "- B"])
    service = MemoryService(root_dir=tmp_path, compressor=compressor)

    service.compress_and_append("../private_1", "a")
    service.compress_and_append("private_1", "b")

    assert service.read("../private_1") == "- A\n"
    assert service.read("private_1") == "- B\n"
    assert sorted(path.name for path in (tmp_path / "sessions").glob("*.md")) == [
        "..%2Fprivate_1.md",
        "private_1.md",
    ]
    assert not (tmp_path / "private_1.md").exists()


def test_blank_input_does_not_call_llm_or_append(tmp_path: Path) -> None:
    compressor = StubCompressor()
    service = MemoryService(root_dir=tmp_path, compressor=compressor)

    result = service.compress_and_append("private_1", " \n\t ")

    assert result.content_markdown == ""
    assert result.added_count == 0
    assert compressor.calls == []
    assert list((tmp_path / "sessions").glob("*.md")) == []


def test_llm_failure_bubbles_to_router_boundary(tmp_path: Path) -> None:
    service = MemoryService(root_dir=tmp_path, compressor=StubCompressor(fail=True))

    with pytest.raises(RuntimeError):
        service.compress_and_append("private_1", "msg")


def test_normalize_bullets_preserves_timestamped_log_lines(tmp_path: Path) -> None:
    compressor = StubCompressor(outputs=["[2026-06-17T10:00:00+08:00] user: 记住我喜欢日志式记忆"])
    service = MemoryService(root_dir=tmp_path, compressor=compressor)

    result = service.compress_and_append("private_1", "raw")

    assert result.added_markdown == "- [2026-06-17T10:00:00+08:00] user: 记住我喜欢日志式记忆"
    assert result.content_markdown == "- [2026-06-17T10:00:00+08:00] user: 记住我喜欢日志式记忆\n"


def test_read_missing_user_memory_returns_empty_template(tmp_path: Path) -> None:
    service = MemoryService(root_dir=tmp_path, compressor=StubCompressor())

    assert service.read_user_memory("123") == USER_MEMORY_EMPTY_TEMPLATE


def test_read_user_memory_page_returns_original_markdown_slice(tmp_path: Path) -> None:
    service = MemoryService(root_dir=tmp_path, compressor=StubCompressor())
    (tmp_path / "users").mkdir(parents=True, exist_ok=True)
    (tmp_path / "users" / "123.md").write_text(
        "## 用户画像\n- A\n\n## 相关记忆\n- B\n- C\n",
        encoding="utf-8",
    )

    page = service.read_user_memory_page("123", start_line=1, line_count=3)

    assert page.user_id == "123"
    assert page.content_markdown == "- A\n\n## 相关记忆\n"
    assert page.start_line == 1
    assert page.line_count == 3
    assert page.total_lines == 6
    assert page.has_more is True


def test_read_user_memory_page_returns_empty_slice_when_start_line_out_of_range(tmp_path: Path) -> None:
    service = MemoryService(root_dir=tmp_path, compressor=StubCompressor())

    page = service.read_user_memory_page("123", start_line=10, line_count=5)

    assert page.content_markdown == ""
    assert page.total_lines == 3
    assert page.has_more is False


def test_read_user_memory_page_rejects_invalid_pagination(tmp_path: Path) -> None:
    service = MemoryService(root_dir=tmp_path, compressor=StubCompressor())

    with pytest.raises(ValueError, match="start_line must be non-negative"):
        service.read_user_memory_page("123", start_line=-1, line_count=5)

    with pytest.raises(ValueError, match="line_count must be positive"):
        service.read_user_memory_page("123", start_line=0, line_count=0)


def test_compress_schedules_user_memory_update_from_message_user_id(tmp_path: Path) -> None:
    scheduler = InlineScheduler()
    synthesizer = StubUserMemorySynthesizer()
    service = MemoryService(
        root_dir=tmp_path,
        compressor=StubCompressor(outputs=["- [2026-06-18T10:00:00+08:00] 用户 123 说喜欢中文注释"]),
        user_memory_synthesizer=synthesizer,
        user_memory_scheduler=scheduler,
    )

    result = service.compress_and_append(
        "group_1",
        '[2026-06-18T10:00:00+08:00] user: <message user_id="123">我喜欢中文注释</message>',
    )

    assert result.added_count == 1
    assert len(scheduler.jobs) == 1
    assert service.read_user_memory("123") == USER_MEMORY_EMPTY_TEMPLATE

    scheduler.run_all()

    assert service.read_user_memory("123") == "## 用户画像\n- 用户喜欢中文注释\n\n## 相关记忆\n- 正在重构 memory\n"
    assert (tmp_path / "users" / "123.md").read_text(encoding="utf-8") == (
        "## 用户画像\n- 用户喜欢中文注释\n\n## 相关记忆\n- 正在重构 memory\n"
    )
    assert list(tmp_path.glob("123.md")) == []
    current_markdown, new_logs_markdown = synthesizer.calls[0]
    assert current_markdown == USER_MEMORY_EMPTY_TEMPLATE
    assert '<message user_id="123">我喜欢中文注释</message>' in new_logs_markdown
    assert "用户 123 说喜欢中文注释" in new_logs_markdown


def test_user_memory_filename_uses_readable_user_id_with_path_escape_encoding(tmp_path: Path) -> None:
    scheduler = InlineScheduler()
    service = MemoryService(
        root_dir=tmp_path,
        compressor=StubCompressor(outputs=["- 用户异常 ID 也不能逃逸目录"]),
        user_memory_synthesizer=StubUserMemorySynthesizer(
            outputs=["## 用户画像\n- 路径字符被编码\n\n## 相关记忆"]
        ),
        user_memory_scheduler=scheduler,
    )

    service.compress_and_append(
        "group_1",
        '[2026-06-18T10:00:00+08:00] user: <message user_id="../123">测试</message>',
    )
    scheduler.run_all()

    assert service.read_user_memory("../123") == "## 用户画像\n- 路径字符被编码\n\n## 相关记忆\n"
    assert (tmp_path / "users" / "..%2F123.md").exists()
    assert not (tmp_path / "123.md").exists()


def test_group_chat_updates_multiple_user_memories_without_crossing_raw_messages(tmp_path: Path) -> None:
    scheduler = InlineScheduler()
    synthesizer = StubUserMemorySynthesizer(
        outputs=[
            "## 用户画像\n- 用户 123 喜欢日志\n\n## 相关记忆",
            "## 用户画像\n- 用户 456 喜欢检索\n\n## 相关记忆",
        ]
    )
    service = MemoryService(
        root_dir=tmp_path,
        compressor=StubCompressor(outputs=["- 群聊里 123 喜欢日志\n- 群聊里 456 喜欢检索"]),
        user_memory_synthesizer=synthesizer,
        user_memory_scheduler=scheduler,
    )

    service.compress_and_append(
        "group_1",
        "\n".join(
            [
                '[2026-06-18T10:00:00+08:00] user: <message user_id="123">我喜欢日志</message>',
                '[2026-06-18T10:01:00+08:00] user: <message user_id="456">我喜欢检索</message>',
            ]
        ),
    )

    assert len(scheduler.jobs) == 2
    scheduler.run_all()

    assert service.read_user_memory("123") == "## 用户画像\n- 用户 123 喜欢日志\n\n## 相关记忆\n"
    assert service.read_user_memory("456") == "## 用户画像\n- 用户 456 喜欢检索\n\n## 相关记忆\n"
    first_raw_block = synthesizer.calls[0][1].split("【本轮无损压缩日志】", maxsplit=1)[0]
    second_raw_block = synthesizer.calls[1][1].split("【本轮无损压缩日志】", maxsplit=1)[0]
    assert 'user_id="123"' in first_raw_block
    assert 'user_id="456"' not in first_raw_block
    assert 'user_id="456"' in second_raw_block
    assert 'user_id="123"' not in second_raw_block


def test_user_memory_failure_does_not_rollback_session_log(tmp_path: Path) -> None:
    scheduler = InlineScheduler()
    service = MemoryService(
        root_dir=tmp_path,
        compressor=StubCompressor(outputs=["- 用户 123 说继续保留无损日志"]),
        user_memory_synthesizer=StubUserMemorySynthesizer(fail=True),
        user_memory_scheduler=scheduler,
    )

    result = service.compress_and_append(
        "private_123",
        '[2026-06-18T10:00:00+08:00] user: <message user_id="123">继续保留无损日志</message>',
    )
    scheduler.run_all()

    assert result.content_markdown == "- 用户 123 说继续保留无损日志\n"
    assert service.read("private_123") == "- 用户 123 说继续保留无损日志\n"
    assert service.read_user_memory("123") == USER_MEMORY_EMPTY_TEMPLATE


def test_shutdown_delegates_to_user_memory_scheduler(tmp_path: Path) -> None:
    scheduler = InlineScheduler()
    service = MemoryService(
        root_dir=tmp_path,
        compressor=StubCompressor(),
        user_memory_synthesizer=StubUserMemorySynthesizer(),
        user_memory_scheduler=scheduler,
    )

    service.shutdown(timeout_seconds=3.5)

    assert scheduler.shutdown_calls == [3.5]


def test_session_markdown_is_truncated_to_last_max_lines(tmp_path: Path) -> None:
    compressor = StubCompressor(outputs=["- 第一条\n- 第二条", "- 第三条\n- 第四条"])
    service = MemoryService(root_dir=tmp_path, compressor=compressor, session_max_lines=3)

    service.compress_and_append("private_1", "first")
    result = service.compress_and_append("private_1", "second")

    assert result.added_markdown == "- 第三条\n- 第四条"
    assert result.added_count == 2
    assert result.content_markdown == "- 第二条\n- 第三条\n- 第四条\n"
    assert service.read("private_1") == "- 第二条\n- 第三条\n- 第四条\n"


def test_session_markdown_is_not_truncated_when_under_limit(tmp_path: Path) -> None:
    compressor = StubCompressor(outputs=["- 第一条", "- 第二条"])
    service = MemoryService(root_dir=tmp_path, compressor=compressor, session_max_lines=5)

    service.compress_and_append("private_1", "first")
    result = service.compress_and_append("private_1", "second")

    assert result.content_markdown == "- 第一条\n- 第二条\n"
