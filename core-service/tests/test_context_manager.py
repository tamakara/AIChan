from pathlib import Path

import pytest

from core_service.adapters.protocol import SkillDocument
from core_service.services.context_manager import ContextManager
from core_service.services.skills import LocalSkillRepository


@pytest.mark.asyncio
async def test_context_snapshot_has_stable_layer_order_and_live_skills(tmp_path: Path) -> None:
    prompt = tmp_path / "system.md"
    prompt.write_text("base", encoding="utf-8")
    skill_dir = tmp_path / "skills" / "style"
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text('---\nid: style\nversion: "1"\nenabled: true\n---\nold style', encoding="utf-8")
    repository = LocalSkillRepository(tmp_path / "skills", 1024, 4096)
    manager = ContextManager(system_prompt_path=prompt, skills=repository, memory_client=None, compress_every_n_records=10, max_turns=3)
    await manager.create("qq:main:private:1", {"adapter_id": "qq", "instance_id": "main"})
    adapter_skill = SkillDocument(id="qq", version="1", content="channel")

    first = await manager.snapshot("qq:main:private:1", [{"role": "user", "content": "hello"}], [adapter_skill])
    assert [item["content"] for item in first.messages[:4]] == [
        "base",
        '<skill id="style" version="1">\nold style\n</skill>',
        '<skill id="qq" version="1">\nchannel\n</skill>',
        '<session session_id="qq:main:private:1" max_turn="3" adapter_id="qq" instance_id="main" />',
    ]

    skill_file.write_text('---\nid: style\nversion: "2"\nenabled: true\n---\nnew style', encoding="utf-8")
    second = await manager.snapshot("qq:main:private:1", [], [adapter_skill])
    assert "new style" in second.messages[1]["content"]


@pytest.mark.asyncio
async def test_queued_message_increments_revision(tmp_path: Path) -> None:
    prompt = tmp_path / "system.md"
    prompt.write_text("base", encoding="utf-8")
    manager = ContextManager(system_prompt_path=prompt, skills=LocalSkillRepository(tmp_path / "missing", 1024, 4096), memory_client=None, compress_every_n_records=10, max_turns=3)
    await manager.create("s", {})
    before = await manager.snapshot("s", [], [])
    await manager.queue("s", "<messages />", {"a" * 64})
    after = await manager.snapshot("s", [], [])
    assert after.revision == before.revision + 1
    assert await manager.drain_queued("s") == ["<messages />"]
    assert "a" * 64 in after.allowed_file_refs


@pytest.mark.asyncio
async def test_final_commit_is_atomic_with_queued_messages(tmp_path: Path) -> None:
    prompt = tmp_path / "system.md"
    prompt.write_text("base", encoding="utf-8")
    manager = ContextManager(system_prompt_path=prompt, skills=LocalSkillRepository(tmp_path / "missing", 1024, 4096), memory_client=None, compress_every_n_records=10, max_turns=3)
    await manager.create("s", {})
    await manager.queue("s", "<messages><message /></messages>", set())
    queued = await manager.commit_if_no_queue("s", [{"role": "assistant", "content": "old"}])
    assert queued == ["<messages><message /></messages>"]
    snapshot = await manager.snapshot("s", [], [])
    assert all(item.get("content") != "old" for item in snapshot.messages)
