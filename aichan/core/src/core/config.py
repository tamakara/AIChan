from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # MCPHub 连接配置（逗号分隔多个 SSE 地址）
    mcp_server_urls: str = "http://localhost:9000/mcp/sse"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


# 模块级配置单例：项目其他位置直接 `from core.config import settings` 使用。
settings = AppSettings()
