import logging
from time import perf_counter
from typing import Any


LOGGER_NAME_PREFIX = "hub_service"
EVENT_LABELS = {
    "hub_app.boot": "服务初始化",
    "hub_app.ready": "服务启动完成",
    "hub_app.stopping": "服务停止中",
    "hub_app.stopped": "服务已停止",
    "hub.consumer_started": "事件消费者已启动",
    "hub.consumer_stopped": "事件消费者已停止",
    "hub.event_dropped": "事件消息已丢弃",
    "hub.event_retry": "事件处理失败将重试",
    "hub.event_skipped": "事件消息已跳过",
    "hub.event_submitted": "事件已提交调度",
    "hub.session_run_started": "会话调度开始",
    "hub.session_run_failed": "会话调度失败",
    "hub.session_run_completed": "会话调度完成",
    "hub.session_reply_discarded": "会话回复已丢弃",
    "hub.downstream_called": "下游请求完成",
    "hub.reply_enqueued": "回复动作已入队",
}
FIELD_LABELS = {
    "agent_id": "Agent",
    "session_id": "会话",
    "message_id": "消息",
    "event_id": "事件",
    "message_type": "消息类型",
    "events_stream": "事件流",
    "events_group": "事件组",
    "actions_stream": "动作流",
    "status": "状态",
    "reason": "原因",
    "elapsed_ms": "耗时",
    "message_count": "消息数",
    "message_mode": "消息模式",
    "reply_len": "回复长度",
    "status_code": "状态码",
    "url": "地址",
}
DEFAULT_HIGHLIGHT_KEYS = (
    "agent_id",
    "session_id",
    "message_id",
    "event_id",
    "status",
    "reason",
    "elapsed_ms",
    "status_code",
)
EVENT_HIGHLIGHT_KEYS = {
    "hub_app.boot": ("events_stream", "events_group", "actions_stream"),
    "hub_app.ready": ("elapsed_ms",),
    "hub_app.stopped": ("elapsed_ms",),
    "hub.event_dropped": ("message_id", "reason"),
    "hub.event_retry": ("message_id", "elapsed_ms"),
    "hub.event_skipped": ("message_id", "message_type", "reason"),
    "hub.event_submitted": ("message_id", "session_id", "event_id"),
    "hub.session_run_started": ("agent_id", "session_id", "message_count", "message_mode"),
    "hub.session_run_failed": ("agent_id", "session_id", "elapsed_ms"),
    "hub.session_run_completed": ("agent_id", "session_id", "reply_len", "elapsed_ms"),
    "hub.session_reply_discarded": ("agent_id", "session_id", "reason", "elapsed_ms"),
    "hub.downstream_called": ("session_id", "elapsed_ms", "status"),
    "hub.reply_enqueued": ("session_id", "reply_len", "elapsed_ms"),
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
    # 运行时日志统一收口到 hub_service.*，避免框架/HTTP 库噪声干扰业务排障。
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
