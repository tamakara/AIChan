from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from urllib.parse import unquote
from uuid import uuid4

import yaml
from fastapi import FastAPI, WebSocket

from .config import SessionRule, get_settings
from .hub_client import HubClient
from .media import HubMediaClient
from .message_xml import OutboundFile, OutboundMessage, OutboundPoke, event_to_xml, reply_to_items
from .napcat import NapcatGateway, is_at_bot


def create_app() -> FastAPI:
    settings = get_settings()
    media = HubMediaClient(settings.adapter.hub_http_url, settings.adapter.hub_token)
    napcat = NapcatGateway(settings.adapter.action_timeout_seconds)
    rules = {
        (item.type, str(item.id)): item
        for item in settings.adapter.session_whitelist if item.enabled
    }

    async def deliver_reply(payload: dict[str, Any]) -> None:
        conversation_type, conversation_id = _route_from_session(
            str(payload["session_id"]), settings.adapter.adapter_id, settings.adapter.instance_id,
        )
        items = await reply_to_items(str(payload["output_xml"]), media)
        for item in items:
            if isinstance(item, OutboundPoke):
                params: dict[str, Any] = {"user_id": int(item.target_id)}
                if conversation_type == "group":
                    params["group_id"] = int(conversation_id)
                await napcat.action("send_poke", params)
            elif isinstance(item, OutboundFile):
                action = "upload_group_file" if conversation_type == "group" else "upload_private_file"
                peer_key = "group_id" if conversation_type == "group" else "user_id"
                await napcat.action(action, {peer_key: int(conversation_id), "file": item.file, "name": item.name})
            else:
                segments = list(item.segments)
                if conversation_type == "group" and item.mention and item.target_id:
                    segments = [{"type": "at", "data": {"qq": item.target_id}}, {"type": "text", "data": {"text": " "}}, *segments]
                action = "send_group_msg" if conversation_type == "group" else "send_private_msg"
                peer_key = "group_id" if conversation_type == "group" else "user_id"
                await napcat.action(action, {peer_key: int(conversation_id), "message": segments, "auto_escape": False})

    async def invoke_capability(capability: str, arguments: dict[str, Any]) -> Any:
        if capability == "user.get":
            return await napcat.action("get_stranger_info", {
                "user_id": int(arguments["user_id"]), "no_cache": True,
            })
        if capability == "message.history":
            message_type = str(arguments["message_type"])
            peer_id = int(arguments["peer_id"])
            limit = int(arguments.get("limit", 20))
            before = int(arguments.get("before_message_id", 0) or 0)
            if message_type == "group":
                return await napcat.action("get_group_msg_history", {
                    "group_id": peer_id, "count": limit, "message_seq": before,
                })
            return await napcat.action("get_friend_msg_history", {
                "user_id": peer_id, "count": limit, "message_seq": before,
            })
        raise ValueError("unsupported QQ capability")

    registration = _registration(settings.adapter.adapter_id, settings.adapter.instance_id, settings.adapter.session_whitelist)
    hub = HubClient(
        settings.adapter.hub_ws_url, settings.adapter.hub_token, registration,
        deliver_reply, invoke_capability, settings.adapter.ack_timeout_seconds,
        settings.adapter.reconnect_seconds,
    )

    async def on_napcat_event(event: dict[str, Any]) -> None:
        route = _event_route(event)
        if route is None:
            return
        conversation_type, conversation_id = route
        rule = rules.get(route)
        user_id = _int(event.get("user_id"))
        self_id = _int(event.get("self_id"))
        if rule is None or user_id is None or user_id == self_id or user_id in rule.blocked_user_ids:
            return
        is_message = event.get("post_type") == "message"
        is_poke = event.get("post_type") == "notice" and event.get("sub_type") == "poke" and _int(event.get("target_id")) == self_id
        if not is_message and not is_poke:
            return
        if conversation_type == "group" and rule.require_mention and is_message and not is_at_bot(event):
            return
        input_xml = await event_to_xml(event, media, napcat)
        await hub.publish({
            "event_id": str(event.get("message_id") or uuid4()),
            "conversation_type": conversation_type,
            "conversation_id": conversation_id,
            "bot_id": str(event.get("self_id", "")),
            "input_xml": input_xml,
        })

    napcat.set_event_handler(on_napcat_event)
    app = FastAPI(title="aichan-qq-adapter", version="1.0.0")
    hub_task: asyncio.Task[None] | None = None

    @app.get("/healthz")
    async def healthz() -> dict[str, object]:
        return {"status": "ok", "napcat_connected": napcat.connected}

    @app.websocket("/onebot/v11/ws")
    async def onebot_ws(websocket: WebSocket) -> None:
        await napcat.handle(websocket)

    @app.on_event("startup")
    async def startup() -> None:
        nonlocal hub_task
        hub_task = asyncio.create_task(hub.run(), name="aichan-qq-adapter-hub-client")

    @app.on_event("shutdown")
    async def shutdown() -> None:
        await hub.stop()
        if hub_task is not None:
            hub_task.cancel()
            await asyncio.gather(hub_task, return_exceptions=True)
        await media.aclose()

    return app


def _registration(adapter_id: str, instance_id: str, rules: tuple[SessionRule, ...]) -> dict[str, Any]:
    skill_path = Path.cwd() / "skills" / "qq-channel" / "SKILL.md"
    raw = skill_path.read_text(encoding="utf-8")
    frontmatter, content = raw[4:].split("\n---\n", 1)
    skill_meta = yaml.safe_load(frontmatter)
    return {
        "adapter_id": adapter_id, "instance_id": instance_id, "display_name": "QQ / NapCat",
        "config_schema": {"type": "object", "properties": {
            "session_whitelist": {"type": "array"}, "action_timeout_seconds": {"type": "number"},
        }},
        "config_summary": {"session_count": len(rules)},
        "capabilities": [
            {"name": "user.get", "description": "查询 QQ 用户资料", "input_schema": {"type": "object", "required": ["user_id"]}, "output_schema": {}},
            {"name": "message.history", "description": "查询 QQ 历史消息", "input_schema": {"type": "object", "required": ["message_type", "peer_id"]}, "output_schema": {}},
        ],
        "extensions": [
            {"namespace": "qq", "name": "face", "directions": ["input", "output"], "parameters_schema": {"type": "object", "required": ["name"]}},
            {"namespace": "qq", "name": "mface", "directions": ["input"], "parameters_schema": {"type": "object"}},
            {"namespace": "qq", "name": "poke", "directions": ["input", "output"], "parameters_schema": {"type": "object", "required": ["target_id"]}},
        ],
        "skills": [{**skill_meta, "content": content.strip()}],
    }


def _event_route(event: dict[str, Any]) -> tuple[str, str] | None:
    if event.get("message_type") == "private":
        return "private", str(event.get("user_id", ""))
    group_id = event.get("group_id")
    if group_id is not None:
        return "group", str(group_id)
    if event.get("post_type") == "notice" and event.get("user_id") is not None:
        return "private", str(event["user_id"])
    return None


def _route_from_session(session_id: str, adapter_id: str, instance_id: str) -> tuple[str, str]:
    parts = [unquote(part) for part in session_id.split(":", 3)]
    if len(parts) != 4 or parts[0:2] != [adapter_id, instance_id]:
        raise ValueError("reply is not for this QQ adapter instance")
    return parts[2], parts[3]


def _int(value: object) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


app = create_app()
