import logging
from time import perf_counter
from typing import Any


LOGGER_NAME_PREFIX = "memory_service"
EVENT_LABELS = {
    "memory_app.boot": "记忆服务初始化",
    "memory_app.ready": "记忆服务启动完成",
    "memory.compress_completed": "记忆压缩完成",
    "memory.user_memory_updated": "用户记忆更新完成",
    "memory.user_memory_failed": "用户记忆更新失败",
}
FIELD_LABELS = {
    "root_dir": "目录",
    "session_id": "会话",
    "user_id": "用户",
    "added_count": "新增条目",
    "elapsed_ms": "耗时",
}
DEFAULT_HIGHLIGHT_KEYS = ("session_id", "added_count", "elapsed_ms")
EVENT_HIGHLIGHT_KEYS = {
    "memory_app.boot": ("root_dir",),
    "memory_app.ready": ("elapsed_ms",),
    "memory.compress_completed": ("session_id", "added_count", "elapsed_ms"),
    "memory.user_memory_updated": ("user_id", "elapsed_ms"),
    "memory.user_memory_failed": ("user_id",),
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


def log_exception(logger: logging.Logger, event: str, **fields: Any) -> None:
    logger.exception(_build_log_message(event, fields))


def _build_log_message(event: str, fields: dict[str, Any]) -> str:
    label = EVENT_LABELS.get(event, event)
    if not fields:
        return label

    highlights: list[str] = []
    for key in EVENT_HIGHLIGHT_KEYS.get(event, DEFAULT_HIGHLIGHT_KEYS):
        if key not in fields:
            continue
        label_text = FIELD_LABELS.get(key, key)
        highlights.append(f"{label_text}={_format_field_value_with_unit(key, fields[key])}")
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
    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi", "httpx", "httpcore"):
        framework_logger = logging.getLogger(logger_name)
        framework_logger.handlers.clear()
        framework_logger.propagate = False
        framework_logger.setLevel(logging.CRITICAL + 1)
