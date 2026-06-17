from pathlib import Path

import pytest

from memory_service.services.memory import MemoryService


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
    assert len(list(tmp_path.glob("*.md"))) == 1


def test_consecutive_compress_appends_instead_of_overwriting(tmp_path: Path) -> None:
    compressor = StubCompressor(outputs=["- 第一条", "- 第二条"])
    service = MemoryService(root_dir=tmp_path, compressor=compressor)

    service.compress_and_append("private_1", "first")
    result = service.compress_and_append("private_1", "second")

    assert result.content_markdown == "- 第一条\n- 第二条\n"


def test_different_sessions_are_isolated_by_hash_files(tmp_path: Path) -> None:
    compressor = StubCompressor(outputs=["- A", "- B"])
    service = MemoryService(root_dir=tmp_path, compressor=compressor)

    service.compress_and_append("../private_1", "a")
    service.compress_and_append("private_1", "b")

    assert service.read("../private_1") == "- A\n"
    assert service.read("private_1") == "- B\n"
    assert sorted(path.name for path in tmp_path.glob("*.md")) != ["private_1.md"]
    assert len(list(tmp_path.glob("*.md"))) == 2


def test_blank_input_does_not_call_llm_or_append(tmp_path: Path) -> None:
    compressor = StubCompressor()
    service = MemoryService(root_dir=tmp_path, compressor=compressor)

    result = service.compress_and_append("private_1", " \n\t ")

    assert result.content_markdown == ""
    assert result.added_count == 0
    assert compressor.calls == []
    assert list(tmp_path.glob("*.md")) == []


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

