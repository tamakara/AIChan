from pathlib import Path

from skill_service.registry import SkillRegistry
from skill_service.schemas import AdapterSkillSnapshot, SkillDocument


def test_resolve_combines_system_and_active_adapter(tmp_path: Path) -> None:
    root = tmp_path / "system" / "protocol"
    root.mkdir(parents=True)
    (root / "SKILL.md").write_text(
        "---\nid: protocol\nversion: '1'\ndescription: core\nenabled: true\n---\ncore rules", encoding="utf-8"
    )
    registry = SkillRegistry(tmp_path / "system", 1024, 4096)
    registry.replace_adapter(AdapterSkillSnapshot(adapter_id="qq", instance_id="main", skills=[
        SkillDocument(id="qq", version="1", content="qq rules")
    ]))
    assert [item.id for item in registry.resolve("qq", "main")] == ["protocol", "qq"]
    registry.deactivate_adapter("qq", "main")
    assert [item.id for item in registry.resolve("qq", "main")] == ["protocol"]
