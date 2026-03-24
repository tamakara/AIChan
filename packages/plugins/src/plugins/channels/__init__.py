"""channels 子包：承载交互类插件（输入输出通道）。"""

from plugins.base import BaseChannelPlugin
from plugins.channels.cli import CLIChannelPlugin

__all__ = ["BaseChannelPlugin", "CLIChannelPlugin"]
