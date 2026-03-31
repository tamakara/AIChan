from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException

from core.logger import logger

from .models import GatewayConfig, GatewayRegisterRequest
from .onboarding import brain_onboarding_process, handle_onboarding_done
from .state import (
    gateway_config_registry,
    gateway_onboarding_tasks,
)

# 注册中心路由：仅负责网关接入、工具映射与事件感知，不负责信号触发。
registry_router = APIRouter(tags=["registry"])


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


@registry_router.post("/internal/registry/register")
async def register_gateway(payload: GatewayRegisterRequest) -> dict[str, Any]:
    """
    网关注册入口。

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
        lambda task, gateway_name=config.name: handle_onboarding_done(task, gateway_name)
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
