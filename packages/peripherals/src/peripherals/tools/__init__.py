"""tools 子包：承载功能类外设（可被 LLM 调用的动作能力）。"""


from peripherals.tools.time_tool import CurrentTimeToolPeripheral, get_current_time

__all__ = ["CurrentTimeToolPeripheral", "get_current_time"]
