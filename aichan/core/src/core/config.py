"""
项目配置读取模块。

设计目标：
1. 统一从环境变量加载配置，避免散落读取；
2. 使用 pydantic-settings 做类型校验与默认值管理；
3. 通过模块级 `settings` 单例供全局复用。
"""

from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """
    应用全局配置对象。

    所有字段统一从环境变量读取，避免在代码里硬编码敏感参数。
    """

    # 大模型访问配置
    llm_api_type: Literal["openai", "google"] = "openai"
    llm_api_key: SecretStr
    llm_base_url: str
    llm_model_name: str
    llm_temperature: float = Field(default=0.5, ge=0.0, le=2.0)

    # MCPHub 连接配置（支持逗号分隔字符串，预处理后为 URL 列表）。
    mcp_server_endpoints: list[str]
    # MCP 首次连接失败后的重试间隔（秒），最小值为 1 秒。
    mcp_connect_retry_seconds: float = Field(default=2.0, ge=1.0)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("mcp_server_endpoints", mode="before")
    @classmethod
    def _normalize_mcp_server_endpoints(cls, value: object) -> list[str]:
        """
        统一规范 MCP 端点配置输入。

        支持输入：
        1. 逗号分隔字符串（环境变量常见形态）；
        2. 字符串列表/元组（程序内传参形态）。
        """
        endpoints: list[str] = []

        if isinstance(value, str):
            endpoints = [item.strip() for item in value.split(",") if item.strip()]
        elif isinstance(value, (list, tuple)):
            for item in value:
                if not isinstance(item, str):
                    raise TypeError("mcp_server_endpoints 列表项必须是字符串")
                clean_item = item.strip()
                if clean_item:
                    endpoints.append(clean_item)
        else:
            raise TypeError("mcp_server_endpoints 必须是字符串或字符串列表")

        if not endpoints:
            raise ValueError("mcp_server_endpoints 至少需要一个有效 URL")
        return endpoints


# 模块级配置单例：项目其他位置直接 `from core.config import settings` 使用。
settings = AppSettings()
