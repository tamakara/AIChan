import logging
from time import perf_counter
from typing import Any


LOGGER_NAME_PREFIX = "napcat_mcp"
EVENT_LABELS = {
    "napcat_mcp.boot": "服务初始化",
    "napcat_mcp.ready": "服务启动完成",
    "napcat_mcp.stopping": "服务停止中",
    "napcat_mcp.stopped": "服务已停止",
    "napcat_mcp.ws_connected": "NapCat WS 已连接",
    "napcat_mcp.ws_disconnected": "NapCat WS 已断开",
    "napcat_mcp.ws_action_completed": "OneBot Action 调用完成",
    "napcat_mcp.ws_action_timeout": "OneBot Action 调用超时",
}
FIELD_LABELS = {
    "action_type": "动作类型",
    "status": "状态",
    "elapsed_ms": "耗时",
}
DEFAULT_HIGHLIGHT_KEYS = (
    "action_type",
    "status",
    "elapsed_ms",
)
EVENT_HIGHLIGHT_KEYS = {
    "napcat_mcp.boot": (),
    "napcat_mcp.ready": ("elapsed_ms",),
    "napcat_mcp.stopped": ("elapsed_ms",),
    "napcat_mcp.ws_action_completed": ("action_type", "status", "elapsed_ms"),
    "napcat_mcp.ws_action_timeout": ("action_type", "elapsed_ms"),
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


def log_exception(logger: logging.Logger, event: str, **fields: Any) -> None:
    logger.exception(_build_log_message(event, fields))


def _build_log_message(event: str, fields: dict[str, Any]) -> str:
    label = EVENT_LABELS.get(event, event)
    if not fields:
        return label

    highlights: list[str] = []
    highlight_keys = EVENT_HIGHLIGHT_KEYS.get(event, DEFAULT_HIGHLIGHT_KEYS)
    for key in highlight_keys:
        if key not in fields:
            continue
        label_text = FIELD_LABELS.get(key, key)
        value = str(fields[key]).replace("\n", "\\n")
        if key == "elapsed_ms":
            value = f"{value}ms"
        highlights.append(f"{label_text}={value}")

    if not highlights:
        return label
    return f"{label}（{', '.join(highlights)}）"


def _silence_framework_loggers() -> None:
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
