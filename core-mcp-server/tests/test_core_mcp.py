from pathlib import Path

from core_mcp_server.mcp.client import CoreMcpClient


def test_core_mcp_has_no_adapter_invoke() -> None:
    assert not hasattr(CoreMcpClient, "adapter_invoke")
    catalog = (Path(__file__).resolve().parents[1] / "docker-mcp-catalog.yml").read_text(encoding="utf-8")
    assert "core-mcp-server" in catalog
    assert "adapter_invoke" not in catalog
    assert "tool-mcp-server" not in catalog
