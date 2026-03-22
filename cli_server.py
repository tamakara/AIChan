from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from core.logger import logger
from peripherals.registry import PeripheralRegistry
from synapse.agent import AgentOrchestrator


class ChatRequest(BaseModel):
    """客户端发送到网关的标准请求体。"""

    channel: str = Field(default="cli", description="外设通道名称")
    content: str = Field(..., description="用户输入内容")


class ChatResponse(BaseModel):
    """网关返回给客户端的标准响应体。"""

    reply: str = Field(..., description="模型最终回复文本")


def create_app(orchestrator: AgentOrchestrator) -> FastAPI:
    """
    创建 CLI 网关应用。

    约束：
    - 本文件只负责 HTTP 接口、请求/响应模型和错误码映射。
    - 系统模块组装（peripherals/brain/memory/synapse）由 main.py 提供。
    """
    app = FastAPI(
        title="AIChan 聊天网关",
        description="AIChan 双进程模式下的聊天服务入口",
        version="0.1.0",
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        """健康检查接口，用于探活与启动验证。"""
        return {"status": "ok"}

    @app.post("/chat", response_model=ChatResponse)
    def chat(req: ChatRequest) -> ChatResponse:
        """
        聊天主入口：
        1) 根据 channel 找到外设能力
        2) 让外设把请求转为标准 UserMessage
        3) 交给 synapse -> brain 流程处理
        4) 通过外设返回统一响应
        """
        channel = PeripheralRegistry.get(req.channel)
        if channel is None:
            raise HTTPException(status_code=400, detail=f"未知通道: {req.channel}")

        payload: dict[str, Any] = req.model_dump()

        try:
            user_message = channel.to_user_message(payload)
            reply = orchestrator.process_message(user_message)
        except ValueError as exc:
            # 输入参数不完整或格式不合法时返回 400。
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception(f"聊天处理失败：{exc}")
            raise HTTPException(status_code=500, detail="聊天处理失败") from exc

        # 通道必须实现 from_ai_response，并返回包含 reply 字段的结构。
        channel_payload = channel.from_ai_response(reply)
        if "reply" not in channel_payload:
            raise HTTPException(
                status_code=500,
                detail=f"通道 `{req.channel}` 响应格式错误：缺少 reply 字段",
            )

        return ChatResponse(reply=str(channel_payload["reply"]))

    return app
