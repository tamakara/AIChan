"""peripherals 包：统一外设能力与注册机制。"""


from peripherals.channels.cli import CLIChannelPeripheral
from peripherals.registry import PeripheralRegistry
from peripherals.tools.time_tool import CurrentTimeToolPeripheral

__all__ = [
    "CLIChannelPeripheral",
    "CurrentTimeToolPeripheral",
    "PeripheralRegistry",
]
