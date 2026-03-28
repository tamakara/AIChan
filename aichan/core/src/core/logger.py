from io import StringIO
import shutil
import sys

from loguru import logger
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

# 清理默认日志处理器，避免重复输出。
logger.remove()

# 统一项目日志格式，便于排查跨模块调用链问题。
logger.add(
    sys.stdout,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{module: <18}:{line: >4}</cyan> | <level>{message}</level>",
    level="INFO",
)

def render_panel(text: str, title: str = "LLM Prompt") -> str:
    """使用 Rich Panel 渲染带圆角边框的日志文本。"""
    terminal_width = shutil.get_terminal_size(fallback=(120, 20)).columns
    panel_width = max(60, terminal_width - 2)

    buffer = StringIO()
    console = Console(
        file=buffer,
        width=panel_width,
        color_system=None,
        force_terminal=True,
        highlight=False,
        soft_wrap=True,
    )
    console.print(
        Panel(
            Text(text),
            title=title,
            box=box.ROUNDED,
            padding=(0, 1),
            expand=False,
            safe_box=False,
        )
    )
    return buffer.getvalue().rstrip()


# 对外只导出 logger 与日志样式函数，避免业务层重复实现展示逻辑。
__all__ = ["logger", "render_panel"]
