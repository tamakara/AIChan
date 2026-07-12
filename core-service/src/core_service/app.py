from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI

from .adapters.registry import AdapterRegistry
from .adapters.session_manager import SessionManager
from .adapters.xml_codec import XmlMessageCodec
from .config import get_settings
from .router.router import create_router
from .services.agent import Agent
from .services.context_manager import ContextManager
from .services.file_client import FileServiceClient
from .services.llm_client import LlmClient
from .services.mcp_gateway import McpToolClient
from .services.memory_client import MemoryClient
from .services.observability import create_observability
from .services.skills import LocalSkillRepository


def create_app() -> FastAPI:
    settings = get_settings().core
    codec = XmlMessageCodec(settings.max_xml_bytes)
    mcp = McpToolClient(settings.mcp_sse_url, settings.mcp_auth_token or None)
    memory_http = httpx.AsyncClient(base_url=settings.memory_base_url, timeout=settings.memory_timeout)
    file_http = httpx.AsyncClient(base_url=settings.file_service_url, timeout=30.0)
    memory = MemoryClient(memory_http) if settings.memory_enabled else None
    skills = LocalSkillRepository(Path(settings.skills_root), settings.max_skill_bytes, settings.max_skill_snapshot_bytes)
    contexts = ContextManager(system_prompt_path=Path(settings.system_prompt_path), skills=skills, memory_client=memory, compress_every_n_records=settings.memory_compress_every_n_records, max_turns=settings.max_turns)
    observability = create_observability(settings.langfuse)
    llm = LlmClient(settings.model, settings.openai_api_key, settings.openai_base_url, settings.llm_timeout, settings.llm_max_retries)
    adapters = AdapterRegistry(tokens=settings.adapter_tokens, codec=codec, reserved_tool_names=set(), ack_timeout=settings.ack_timeout_seconds, ack_attempts=settings.ack_max_attempts, capability_timeout=settings.capability_timeout_seconds)
    agent = Agent(llm_client=llm, mcp=mcp, adapters=adapters, contexts=contexts, codec=codec, max_turns=settings.max_turns, max_retries=settings.llm_max_retries, temperature=settings.temperature, observability=observability)
    sessions = SessionManager(agent=agent, adapters=adapters, contexts=contexts, codec=codec, debounce_seconds=settings.debounce_seconds)
    adapters.set_event_handler(sessions.submit_event)
    files = FileServiceClient(file_http)

    async def initialize_mcp() -> None:
        while not mcp.ready:
            try:
                await mcp.initialize()
                adapters.set_reserved_tool_names(mcp.tool_names)
            except Exception:
                logging.getLogger(__name__).exception("MCP gateway 初始化失败，稍后重试")
                await asyncio.sleep(5)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        mcp_task = asyncio.create_task(initialize_mcp())
        yield
        mcp_task.cancel()
        await asyncio.gather(mcp_task, return_exceptions=True)
        await sessions.close()
        await contexts.close()
        await llm.close()
        await memory_http.aclose()
        await file_http.aclose()
        await asyncio.to_thread(observability.flush, settings.langfuse.request_timeout)

    app = FastAPI(title="core-service", version="2.0.0", lifespan=lifespan)
    app.include_router(create_router(adapters=adapters, files=files, ready=lambda: mcp.ready))
    app.state.adapters = adapters
    app.state.contexts = contexts
    app.state.mcp = mcp
    return app
