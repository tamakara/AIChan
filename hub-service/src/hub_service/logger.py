import logging
from time import perf_counter
from typing import Any


LOGGER_NAME_PREFIX = "hub_service"
EVENT_LABELS = {
    "hub_app.boot": "服务初始化",
    "hub_app.ready": "服务启动完成",
    "hub_app.stopping": "服务停止中",
    "hub_app.stopped": "服务已停止",
    "hub.ws_connected": "NapCat WS 已连接",
    "hub.ws_disconnected": "NapCat WS 已断开",
    "hub.ws_action_completed": "OneBot Action 调用完成",
    "hub.ws_action_timeout": "OneBot Action 调用超时",
    "hub.session_run_started": "会话调度开始",
    "hub.session_run_failed": "会话调度失败",
    "hub.session_run_completed": "会话调度完成",
    "hub.downstream_called": "下游请求完成",
    "hub.reply_sent": "回复已发送",
}
FIELD_LABELS = {
    "agent_id": "Agent",
    "session_key": "会话",
    "action_type": "动作类型",
    "event_count": "事件数",
    "status": "状态",
    "reason": "原因",
    "elapsed_ms": "耗时",
    "reply_len": "回复长度",
    "status_code": "状态码",
    "url": "地址",
}
DEFAULT_HIGHLIGHT_KEYS = (
    "agent_id",
    "session_key",
    "action_type",
    "status",
    "reason",
    "elapsed_ms",
)
EVENT_HIGHLIGHT_KEYS = {
    "hub_app.boot": ("agent_url",),
    "hub_app.ready": ("elapsed_ms",),
    "hub_app.stopped": ("elapsed_ms",),
    "hub.ws_action_completed": ("action_type", "status", "elapsed_ms"),
    "hub.ws_action_timeout": ("action_type", "elapsed_ms"),
    "hub.session_run_started": ("agent_id", "session_key", "event_count"),
    "hub.session_run_failed": ("agent_id", "session_key", "elapsed_ms"),
    "hub.session_run_completed": ("agent_id", "session_key", "reply_len", "elapsed_ms"),
    "hub.downstream_called": ("session_key", "elapsed_ms", "status"),
    "hub.reply_sent": ("session_key", "reply_len", "elapsed_ms"),
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
