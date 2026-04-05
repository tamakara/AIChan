import json
from typing import Annotated
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class AppSettings(BaseSettings):
    """
    应用全局配置对象。

    所有字段统一从环境变量读取，避免在代码里硬编码敏感参数。
    """

    # 大模型访问配置（必填）
    llm_api_key: SecretStr
    llm_base_url: str
    llm_model_name: str
    llm_temperature: float

    # MCPHub 连接配置（仅支持 JSON 列表）
    mcp_server_urls: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:9000/mcp/sse"]
    )

    @field_validator("mcp_server_urls", mode="before")
    @classmethod
    def parse_mcp_server_urls(cls, value: object) -> object:
        """
        仅接受两种入参形态：
        - JSON 列表字符串：["http://a/mcp/sse", "http://b/mcp/sse"]
        - Python 列表/元组/集合。
        """
        if isinstance(value, str):
            raw_value = value.strip()
            if not raw_value:
                return []

            try:
                parsed_json = json.loads(raw_value)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    "mcp_server_urls must be a JSON array string, "
                    "for example: [\"http://localhost:9000/mcp/sse\"]"
                ) from exc

            if isinstance(parsed_json, list):
                return [str(item).strip() for item in parsed_json if str(item).strip()]

            raise ValueError(
                "mcp_server_urls must be a JSON array, "
                "for example: [\"http://localhost:9000/mcp/sse\"]"
            )

        if isinstance(value, (list, tuple, set)):
            return [str(item).strip() for item in value if str(item).strip()]

        return value

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


# 模块级配置单例：项目其他位置直接 `from core.config import settings` 使用。
settings = AppSettings()
