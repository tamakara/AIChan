from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # 默认值统一收口在仓库根目录 .env.example，避免代码与部署配置出现双重真相。
    llm_model_name: str
    llm_api_key: str
    llm_base_url: str
    mcp_gateway_sse_url: str
    mcp_gateway_auth_token: str
    host: str
    port: int
    log_level: str

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    # 设置在进程生命周期内固定，缓存后可避免重复解析环境变量与重复校验。
    return Settings() # type: ignore


@lru_cache(maxsize=1)
def get_system_prompt() -> str:
    # 提示词集中放在 /prompts，便于独立迭代角色设定而不改动运行时代码。
    prompt_path = Path(__file__).resolve().parent.parent / "prompts" / "system-prompt.md"
    prompt = prompt_path.read_text(encoding="utf-8").strip()
    if not prompt:
        raise ValueError("System prompt is empty in system-prompt.md")
    return prompt
