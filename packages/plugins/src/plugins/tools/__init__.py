"""tools 子包：承载功能类插件（可被 LLM 调用的动作能力）。"""


from plugins.tools.time_tool import CurrentTimeToolPlugin

__all__ = ["CurrentTimeToolPlugin"]


