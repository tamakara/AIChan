"""plugins 包：统一插件能力与注册机制。"""

from plugins.base import BaseChannelPlugin, BasePlugin, BaseToolPlugin
from plugins.channels.cli import CLIChannelPlugin
from plugins.registry import PluginRegistry
from plugins.tools.time_tool import CurrentTimeToolPlugin

__all__ = [
    "BasePlugin",
    "BaseToolPlugin",
    "BaseChannelPlugin",
    "CLIChannelPlugin",
    "CurrentTimeToolPlugin",
    "PluginRegistry",
]
