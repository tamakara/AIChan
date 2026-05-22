import logging
from time import perf_counter
from typing import Any


LOGGER_NAME_PREFIX = "agent_service"
EVENT_LABELS = {
    "agent_app.boot": "服务初始化",
    "agent_app.ready": "服务启动完成",
    "agent.chat_received": "收到会话请求",
    "agent.chat_completed": "会话处理完成",
    "agent.chat_failed": "会话处理失败",
    "agent.agent_created": "Agent 已创建",
    "agent.run_started": "Agent 执行开始",
    "agent.run_completed": "Agent 执行完成",
    "agent.run_failed": "Agent 执行失败",
    "agent.observability_start_failed": "观测启动失败",
    "agent.observability_generation_failed": "观测记录 generation 失败",
    "agent.observability_tool_failed": "观测记录工具调用失败",
    "agent.observability_finish_failed": "观测结束失败",
    "agent.observability_flush_timeout": "观测 flush 超时",
    "agent.observability_flush_failed": "观测 flush 失败",
    "mcp.registered": "MCP 工具注册完成",
    "mcp.tool_called": "MCP 工具调用完成",
    "llm.request_failed": "模型请求失败",
}
FIELD_LABELS = {
    "agent_id": "Agent",
    "session_id": "会话",
    "turn": "轮次",
    "tool_name": "工具",
    "status": "状态",
    "model": "模型",
    "max_turns": "最大轮次",
    "finish_reason": "结束原因",
    "elapsed_ms": "耗时",
    "reply_len": "回复长度",
    "message_count": "消息数",
    "message_len": "消息长度",
    "tool_count": "工具数",
    "created_new_session": "新建会话",
    "mcp_sse_url": "MCP地址",
    "removed_keys": "移除字段",
    "status_code": "状态码",
    "detail": "详情",
    "run_id": "运行",
    "timeout_seconds": "超时",
}
DEFAULT_HIGHLIGHT_KEYS = (
    "agent_id",
    "session_id",
    "turn",
    "tool_name",
    "status",
    "elapsed_ms",
    "finish_reason",
    "status_code",
)
EVENT_HIGHLIGHT_KEYS = {
    "agent_app.boot": ("model", "max_turns", "mcp_sse_url"),
    "agent.agent_created": ("agent_id", "session_id"),
    "agent.chat_received": ("agent_id", "session_id", "message_count"),
    "agent.chat_completed": ("agent_id", "session_id", "reply_len", "elapsed_ms"),
    "agent.chat_failed": ("agent_id", "session_id", "elapsed_ms"),
    "agent.run_started": ("agent_id", "max_turns", "message_len"),
    "agent.run_completed": ("agent_id", "reply_len", "elapsed_ms"),
    "agent.run_failed": ("agent_id", "elapsed_ms"),
    "agent.observability_start_failed": ("agent_id",),
    "agent.observability_generation_failed": ("run_id", "turn"),
    "agent.observability_tool_failed": ("run_id", "tool_name"),
    "agent.observability_finish_failed": ("run_id", "status"),
    "agent.observability_flush_timeout": ("timeout_seconds",),
    "agent.observability_flush_failed": ("detail",),
    "mcp.registered": ("tool_count", "elapsed_ms"),
    "mcp.tool_called": ("tool_name", "elapsed_ms"),
    "llm.request_failed": ("model", "status_code"),
}


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    _silence_framework_loggers()


def get_logger(component: str) -> logging.Logger:
    return logging.getLogger(f"{LOGGER_NAME_PREFIX}.{component}")


def start_timer() -> float:
    return perf_counter()


def elapsed_ms(started_at: float) -> int:
    return int((perf_counter() - started_at) * 1000)


def log_info(logger: logging.Logger, event: str, **fields: Any) -> None:
    logger.info(_build_log_message(event, fields))


def log_warning(logger: logging.Logger, event: str, **fields: Any) -> None:
    logger.warning(_build_log_message(event, fields))


def log_error(logger: logging.Logger, event: str, **fields: Any) -> None:
    logger.error(_build_log_message(event, fields))


def log_exception(logger: logging.Logger, event: str, **fields: Any) -> None:
    logger.exception(_build_log_message(event, fields))


def _build_log_message(event: str, fields: dict[str, Any]) -> str:
    return _build_human_summary(event, fields)


def _build_human_summary(event: str, fields: dict[str, Any]) -> str:
    label = EVENT_LABELS.get(event, event)
    if not fields:
        return label

    highlights: list[str] = []
    highlight_keys = EVENT_HIGHLIGHT_KEYS.get(event, DEFAULT_HIGHLIGHT_KEYS)
    for key in highlight_keys:
        if key in fields:
            value = fields[key]
            label_text = FIELD_LABELS.get(key, key)
            highlights.append(f"{label_text}={_format_field_value_with_unit(key, value)}")

    if not highlights:
        return label
    return f"{label}（{', '.join(highlights)}）"


def _format_field_value(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).replace("\n", "\\n")


def _format_field_value_with_unit(key: str, value: Any) -> str:
    rendered = _format_field_value(value)
    if key == "elapsed_ms":
        return f"{rendered}ms"
    return rendered


def _silence_framework_loggers() -> None:
    # 运行时日志统一收口到 agent_service.*，屏蔽框架与 HTTP 客户端噪声避免污染诊断信号。
    framework_loggers = (
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
        "fastapi",
        "httpx",
        "httpcore",
    )
    for logger_name in framework_loggers:
        framework_logger = logging.getLogger(logger_name)
        framework_logger.handlers.clear()
        framework_logger.propagate = False
        framework_logger.setLevel(logging.CRITICAL + 1)

