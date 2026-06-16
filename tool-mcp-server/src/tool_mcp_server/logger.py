import logging
from time import perf_counter
from typing import Any


LOGGER_NAME_PREFIX = "tool_mcp"
EVENT_LABELS = {
    "tool_mcp.boot": "服务初始化",
    "tool_mcp.ready": "服务启动完成",
    "tool_mcp.stopping": "服务停止中",
    "tool_mcp.stopped": "服务已停止",
}
FIELD_LABELS = {
    "elapsed_ms": "耗时",
}
DEFAULT_HIGHLIGHT_KEYS = (
    "elapsed_ms",
)
EVENT_HIGHLIGHT_KEYS = {
    "tool_mcp.boot": (),
    "tool_mcp.ready": ("elapsed_ms",),
    "tool_mcp.stopped": ("elapsed_ms",),
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
