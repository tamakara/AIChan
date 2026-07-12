import pytest

from hub_service.services.adapter_registry import AdapterConnection, AdapterRegistry
from hub_service.services.protocol import AdapterRegistration, CapabilityDefinition, Envelope


class Skills:
    async def register(self, registration):
        return None

    async def deactivate(self, adapter_id, instance_id):
        return None


class WebSocket:
    def __init__(self):
        self.sent = []
        self.connection = None

    async def send_json(self, payload):
        self.sent.append(payload)
        if payload["type"] in {"reply.deliver", "capability.invoke"}:
            response_type = "reply.ack" if payload["type"] == "reply.deliver" else "capability.result"
            result = {"ok": True, "result": {"value": 1}}
            self.connection.pending[payload["id"]].set_result(Envelope(
                type=response_type, correlation_id=payload["id"], payload=result,
            ))


def build_registry():
    registry = AdapterRegistry({"qq:main": "token"}, Skills(), 0.1, 3, 0.1)
    websocket = WebSocket()
    registration = AdapterRegistration(
        adapter_id="qq", instance_id="main", display_name="QQ",
        capabilities=[CapabilityDefinition(name="user.get")],
    )
    connection = AdapterConnection(registration, websocket)
    websocket.connection = connection
    registry._connections[("qq", "main")] = connection
    return registry, websocket


@pytest.mark.asyncio
async def test_reply_ack_and_capability_result_are_correlated() -> None:
    registry, websocket = build_registry()
    await registry.deliver_reply(("qq", "main"), "qq:main:private:1", "<reply />")
    result = await registry.invoke(("qq", "main"), "qq:main:private:1", "user.get", {})
    assert result == {"value": 1}
    assert [item["type"] for item in websocket.sent] == ["reply.deliver", "capability.invoke"]


def test_adapter_token_must_be_explicitly_authorized() -> None:
    registry, _ = build_registry()
    assert registry.token_allowed("token") is True
    assert registry.token_allowed("wrong") is False
