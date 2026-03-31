from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MCPServerConfig:
    """
    MCP Server 连接配置。

    字段说明：
    - name: 服务别名，用于工具名前缀与日志定位。
    - sse_url: MCP SSE 隧道地址。
    - required: 是否为强依赖。强依赖连接失败会中断启动。
    """

    name: str
    sse_url: str
    required: bool = True

    def __post_init__(self) -> None:
        clean_name = self.name.strip()
        clean_url = self.sse_url.strip()
        if not clean_name:
            raise ValueError("MCPServerConfig.name 不能为空")
        if not clean_url:
            raise ValueError("MCPServerConfig.sse_url 不能为空")

        # dataclass(frozen=True) 场景下需要使用 object.__setattr__ 回填清洗后的值。
        object.__setattr__(self, "name", clean_name)
        object.__setattr__(self, "sse_url", clean_url)
