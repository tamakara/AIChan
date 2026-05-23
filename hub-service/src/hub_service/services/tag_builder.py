from __future__ import annotations

from typing import Literal


def build_batch_xml(
    *,
    event_xmls: list[str],
    batch_type: Literal["start", "append"],
) -> str:
    # hub 只做编排与批次封装，不改写 adapter 产出的单条事件标签，避免协议层重复转义。
    event_content = "".join(event_xml.strip() for event_xml in event_xmls)
    return f'<batch type="{batch_type}">{event_content}</batch>'

