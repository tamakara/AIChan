import sys
from loguru import logger

# 清理默认日志处理器，避免重复输出。
logger.remove()

# 统一项目日志格式，便于排查跨模块调用链问题。
logger.add(
    sys.stdout,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    level="INFO",
)

# 对外只导出 logger，避免误导入其他名称。
__all__ = ["logger"]
