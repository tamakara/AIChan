from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

import httpx
from fastapi import APIRouter, HTTPException
from httpx_sse import aconnect_sse
from pydantic import AnyHttpUrl, BaseModel, Field

from core.logger import logger

# 注册中心路由：仅负责网关接入、工具映射与事件感知，不负责信号触发。
registry_router = APIRouter(tags=["registry"])

# 全局事件总线：网关 SSE 收到的 message 事件统一写入该队列。
global_event_bus: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
# 动态工具注册表：键为网关名，值为该网关映射出的工具集合与元数据。
gateway_tools_registry: dict[str, dict[str, Any]] = {}
# 网关配置注册表：供 SignalProcessor 和事件触发器查询网关连接信息与类型。
gateway_config_registry: dict[str, "GatewayConfig"] = {}
# 网关后台接入任务表：同名网关重复注册时可安全替换旧任务。
gateway_onboarding_tasks: dict[str, asyncio.Task[Any]] = {}

GatewayType = Literal["channel", "tool"]


@dataclass(slots=True, frozen=True)
class GatewayConfig:
    """注册中心内部统一网关配置对象。"""

    name: str
    gateway_type: GatewayType
    base_url: str
    openapi_path: str
    sse_path: str | None


class GatewayRegisterRequest(BaseModel):
    """网关注册请求体（破坏性升级后版本）。"""

    name: str = Field(..., min_length=1, max_length=100)
    type: GatewayType
    base_url: AnyHttpUrl | str
    openapi_path: str | None = None
    sse_path: str | None = None


def _normalize_path(path: str) -> str:
    """规范化路径，保证以 `/` 开头。"""
    normalized = path.strip()
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    return normalized


def _normalize_gateway_config(payload: GatewayRegisterRequest) -> GatewayConfig:
    """
    将注册请求转换为强约束配置对象。

    约束规则（无兼容分支）：
    1. `channel` 必须提供 `openapi_path` 与 `sse_path`；
    2. `tool` 必须提供 `openapi_path`，且不允许提供 `sse_path`。
    """
    gateway_name = payload.name.strip().lower()
    if not gateway_name:
        raise ValueError("name 不能为空")

    base_url = str(payload.base_url).strip().rstrip("/")
    if not base_url:
        raise ValueError("base_url 不能为空")

    raw_openapi_path = (payload.openapi_path or "").strip()
    if not raw_openapi_path:
        raise ValueError("openapi_path 不能为空")
    openapi_path = _normalize_path(raw_openapi_path)

    gateway_type = payload.type
    raw_sse_path = (payload.sse_path or "").strip()

    if gateway_type == "channel":
        if not raw_sse_path:
            raise ValueError("channel 类型必须提供 sse_path")
        sse_path = _normalize_path(raw_sse_path)
    else:
        if raw_sse_path:
            raise ValueError("tool 类型不允许提供 sse_path")
        sse_path = None

    return GatewayConfig(
        name=gateway_name,
        gateway_type=gateway_type,
        base_url=base_url,
        openapi_path=openapi_path,
        sse_path=sse_path,
    )


def _build_send_tool(
    gateway_name: str,
    config: GatewayConfig,
    spec: dict[str, Any],
) -> dict[str, Any]:
    """
    从网关 OpenAPI 中提取“发送消息”能力并转换为动态工具定义。

    当前策略：
    1. 优先选用 `/v1/messages` 的 POST；
    2. 若不存在，则退化为首个可用 POST 操作。
    """
    paths = spec.get("paths")
    if not isinstance(paths, dict) or not paths:
        raise ValueError("OpenAPI paths 缺失或非法")

    selected_path = "/v1/messages"
    selected_operation: dict[str, Any] | None = None

    preferred_item = paths.get(selected_path)
    if isinstance(preferred_item, dict):
        preferred_post = preferred_item.get("post")
        if isinstance(preferred_post, dict):
            selected_operation = preferred_post

    if selected_operation is None:
        for path, item in paths.items():
            if not isinstance(path, str) or not isinstance(item, dict):
                continue
            post_operation = item.get("post")
            if isinstance(post_operation, dict):
                selected_path = path
                selected_operation = post_operation
                break

    if selected_operation is None:
        raise ValueError("OpenAPI 中未找到可用 POST 操作")

    request_body = selected_operation.get("requestBody", {})
    input_schema = (
        request_body.get("content", {})
        .get("application/json", {})
        .get("schema")
    )
    if not isinstance(input_schema, dict):
        input_schema = {
            "type": "object",
            "properties": {
                "sender": {"type": "string"},
                "text": {"type": "string"},
            },
            "required": ["sender", "text"],
        }

    tool_name = f"send_message_to_{gateway_name}".replace("-", "_")
    return {
        "name": tool_name,
        "description": selected_operation.get("summary")
        or f"向网关 {gateway_name} 发送消息。",
        "gateway": gateway_name,
        "method": "POST",
        "url": f"{config.base_url}{selected_path}",
        "openapi_path": selected_path,
        "operation_id": selected_operation.get("operationId"),
        "input_schema": input_schema,
    }


async def _sync_gateway_tools_loop(gateway_name: str, config: GatewayConfig) -> None:
    """
    工具映射后台循环。

    该任务永不主动退出：
    1. 周期拉取 OpenAPI；
    2. 持续刷新动态工具注册表；
    3. 任意异常均 3 秒后重试。
    """
    openapi_url = f"{config.base_url}{config.openapi_path}"
    while True:
        try:
            logger.info(
                "🔌 [Registry] 拉取 OpenAPI，gateway='{}'，url='{}'",
                gateway_name,
                openapi_url,
            )
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(openapi_url)
                response.raise_for_status()
                spec = response.json()

            if not isinstance(spec, dict):
                raise ValueError("OpenAPI 响应不是 JSON 对象")

            tool = _build_send_tool(gateway_name=gateway_name, config=config, spec=spec)
            gateway_tools_registry[gateway_name] = {
                "gateway_type": config.gateway_type,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "tools": {tool["name"]: tool},
            }
            logger.info(
                "✅ [Registry] 动作映射成功，gateway='{}'，tool='{}'",
                gateway_name,
                tool["name"],
            )

            # 每 60 秒刷新一次映射，保证网关 OpenAPI 变更可自动生效。
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            logger.warning("🛑 [Registry] 工具映射任务取消，gateway='{}'", gateway_name)
            raise
        except Exception as exc:
            logger.error(
                "❌ [Registry] 工具映射失败，gateway='{}'，error='{}'，3 秒后重试",
                gateway_name,
                exc,
            )
            await asyncio.sleep(3)


async def _listen_gateway_sse_loop(gateway_name: str, config: GatewayConfig) -> None:
    """
    通道网关 SSE 感知循环。

    行为约束：
    1. 仅消费 `event == message`；
    2. 解析成功后写入 `global_event_bus`；
    3. 任意异常自动重连，不得影响主进程稳定性。
    """
    if config.sse_path is None:
        raise ValueError("sse_path 缺失，无法启动 SSE 监听")

    sse_url = f"{config.base_url}{config.sse_path}"
    while True:
        try:
            logger.info(
                "📡 [Registry] 建立 SSE 监听，gateway='{}'，url='{}'",
                gateway_name,
                sse_url,
            )
            timeout = httpx.Timeout(connect=10.0, read=None, write=10.0, pool=10.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with aconnect_sse(client, "GET", sse_url) as event_source:
                    async for sse in event_source.aiter_sse():
                        if sse.event != "message":
                            continue

                        # SSE 保活帧或空事件不参与解析，避免产生无意义 JSON 告警。
                        raw_data = (sse.data or "").strip()
                        if not raw_data:
                            logger.debug(
                                "📡 [Registry] 忽略空 message 事件，gateway='{}'，event_id='{}'",
                                gateway_name,
                                sse.id,
                            )
                            continue

                        try:
                            payload = json.loads(raw_data)
                        except json.JSONDecodeError as exc:
                            logger.warning(
                                "⚠️ [Registry] SSE JSON 解析失败，gateway='{}'，error='{}'",
                                gateway_name,
                                exc,
                            )
                            continue

                        if not isinstance(payload, dict):
                            logger.warning(
                                "⚠️ [Registry] SSE 载荷非法（非对象），gateway='{}'",
                                gateway_name,
                            )
                            continue

                        event_record = {
                            "gateway": gateway_name,
                            "event": sse.event,
                            "event_id": sse.id,
                            "payload": payload,
                            "received_at": datetime.now(timezone.utc).isoformat(),
                        }
                        await global_event_bus.put(event_record)
                        logger.info(
                            "📥 [Registry] 收到 message 事件入总线，gateway='{}'，event_id='{}'",
                            gateway_name,
                            sse.id,
                        )
        except asyncio.CancelledError:
            logger.warning("🛑 [Registry] SSE 监听任务取消，gateway='{}'", gateway_name)
            raise
        except Exception as exc:
            logger.error(
                "❌ [Registry] SSE 监听断线，gateway='{}'，error='{}'，3 秒后重连",
                gateway_name,
                exc,
            )
            await asyncio.sleep(3)


async def brain_onboarding_process(gateway_name: str, config: GatewayConfig) -> None:
    """
    网关接入后台主流程。

    - `tool` 网关：仅执行工具映射循环。
    - `channel` 网关：并发执行工具映射与 SSE 感知循环。
    """
    logger.info(
        "🧠 [Registry] 启动网关接入流程，gateway='{}'，type='{}'",
        gateway_name,
        config.gateway_type,
    )
    try:
        if config.gateway_type == "channel":
            await asyncio.gather(
                _sync_gateway_tools_loop(gateway_name=gateway_name, config=config),
                _listen_gateway_sse_loop(gateway_name=gateway_name, config=config),
            )
        else:
            await _sync_gateway_tools_loop(gateway_name=gateway_name, config=config)
    except asyncio.CancelledError:
        logger.warning("🛑 [Registry] 接入流程取消，gateway='{}'", gateway_name)
        raise
    except Exception as exc:
        logger.exception(
            "❌ [Registry] 接入流程异常退出，gateway='{}'，error='{}'",
            gateway_name,
            exc,
        )


def _onboarding_done(task: asyncio.Task[Any], gateway_name: str) -> None:
    """后台任务完成回调：回收任务引用并记录异常。"""
    if gateway_onboarding_tasks.get(gateway_name) is task:
        gateway_onboarding_tasks.pop(gateway_name, None)

    try:
        task.result()
    except asyncio.CancelledError:
        logger.warning("♻️ [Registry] 已替换旧接入任务，gateway='{}'", gateway_name)
    except Exception as exc:
        logger.exception(
            "❌ [Registry] 后台任务异常结束，gateway='{}'，error='{}'",
            gateway_name,
            exc,
        )


@registry_router.post("/internal/registry/register")
async def register_gateway(payload: GatewayRegisterRequest) -> dict[str, Any]:
    """
    网关注册入口（无兼容版本）。

    处理流程：
    1. 严格校验并规范化配置；
    2. 覆盖写入配置注册表；
    3. 启动/替换后台 onboarding 任务；
    4. 立即返回 accepted，不阻塞调用方。
    """
    try:
        config = _normalize_gateway_config(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    gateway_config_registry[config.name] = config

    existing_task = gateway_onboarding_tasks.get(config.name)
    if existing_task is not None and not existing_task.done():
        logger.warning("♻️ [Registry] 重复注册，替换旧任务，gateway='{}'", config.name)
        existing_task.cancel()

    onboarding_task = asyncio.create_task(
        brain_onboarding_process(gateway_name=config.name, config=config),
        name=f"brain-onboarding-{config.name}",
    )
    onboarding_task.add_done_callback(
        lambda task, gateway_name=config.name: _onboarding_done(task, gateway_name)
    )
    gateway_onboarding_tasks[config.name] = onboarding_task

    logger.info(
        "✅ [Registry] 注册受理成功，gateway='{}'，type='{}'，base_url='{}'",
        config.name,
        config.gateway_type,
        config.base_url,
    )
    return {
        "status": "accepted",
        "gateway": config.name,
        "type": config.gateway_type,
        "base_url": config.base_url,
        "openapi_path": config.openapi_path,
        "sse_path": config.sse_path,
    }
