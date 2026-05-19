import logging
from time import perf_counter
from typing import Any


LOGGER_NAME_PREFIX = "adapter_service"
EVENT_LABELS = {
    "adapter_app.boot": "服务初始化",
    "adapter_app.ready": "服务启动完成",
    "adapter_app.stopping": "服务停止中",
    "adapter_app.stopped": "服务已停止",
    "adapter.action_consumer_started": "动作消费者已启动",
    "adapter.action_consumer_stopped": "动作消费者已停止",
    "adapter.action_dropped": "动作消息已丢弃",
    "adapter.action_retry": "动作处理失败将重试",
    "adapter.action_skipped": "动作消息已跳过",
    "adapter.action_handled": "动作处理完成",
    "adapter.ws_connected": "OneBot WS 已连接",
    "adapter.ws_disconnected": "OneBot WS 已断开",
    "adapter.ws_action_completed": "OneBot Action 调用完成",
    "adapter.ws_action_timeout": "OneBot Action 调用超时",
}
FIELD_LABELS = {
    "session_id": "会话",
    "message_id": "消息",
    "action_type": "动作类型",
    "actions_stream": "动作流",
    "actions_group": "动作组",
    "events_stream": "事件流",
    "status": "状态",
    "reason": "原因",
    "elapsed_ms": "耗时",
    "reply_len": "回复长度",
    "user_message_len": "用户消息长度",
    "tool_count": "工具数",
    "status_code": "状态码",
}
DEFAULT_HIGHLIGHT_KEYS = (
    "session_id",
    "message_id",
    "action_type",
    "status",
    "reason",
    "elapsed_ms",
    "status_code",
)
EVENT_HIGHLIGHT_KEYS = {
    "adapter_app.boot": ("events_stream", "actions_stream", "actions_group"),
    "adapter_app.ready": ("elapsed_ms",),
    "adapter_app.stopped": ("elapsed_ms",),
    "adapter.action_dropped": ("message_id", "reason"),
    "adapter.action_retry": ("message_id", "elapsed_ms"),
    "adapter.action_skipped": ("action_type", "reason"),
    "adapter.action_handled": ("session_id", "action_type", "status", "elapsed_ms"),
    "adapter.ws_action_completed": ("action_type", "status", "elapsed_ms"),
    "adapter.ws_action_timeout": ("action_type", "elapsed_ms"),
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
        if key not in fields:
            continue
        label_text = FIELD_LABELS.get(key, key)
        highlights.append(
            f"{label_text}={_format_field_value_with_unit(key, fields[key])}"
        )

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
    # 运行时日志统一收口到 adapter_service.*，避免框架/HTTP 库噪声干扰业务排障。
    framework_loggers = (
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
        "fastapi",
        "httpx",
        "httpcore",
        "websockets",
    )
    for logger_name in framework_loggers:
        framework_logger = logging.getLogger(logger_name)
        framework_logger.handlers.clear()
        framework_logger.propagate = False
        framework_logger.setLevel(logging.CRITICAL + 1)


