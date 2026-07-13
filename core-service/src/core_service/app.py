from __future__ import annotations

import asyncio
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
from .services.builtin_tools import BuiltinTools
from .services.context_manager import ContextManager
from .services.file_cache import FileCache
from .services.llm_client import LlmClient
from .services.memory_client import MemoryClient
from .services.observability import create_observability
from .services.perception import FilePerceptionRouter, PerceptionClient
from .services.skills import LocalSkillRepository


def create_app() -> FastAPI:
    settings = get_settings().core
    codec = XmlMessageCodec(settings.max_xml_bytes)
    memory_http = httpx.AsyncClient(base_url=settings.memory_base_url, timeout=settings.memory_timeout)
    memory = MemoryClient(memory_http) if settings.memory_enabled else None
    skills = LocalSkillRepository(Path(settings.skills_root), settings.max_skill_bytes, settings.max_skill_snapshot_bytes)
    contexts = ContextManager(system_prompt_path=Path(settings.system_prompt_path), skills=skills, memory_client=memory, compress_every_n_records=settings.memory_compress_every_n_records, max_turns=settings.max_turns)
    observability = create_observability(settings.langfuse)
    llm = LlmClient(settings.model, settings.openai_api_key, settings.openai_base_url, settings.llm_timeout, settings.llm_max_retries)
    cache = FileCache(
        root_dir=Path(settings.file_cache.root_dir),
        ttl_seconds=settings.file_cache.ttl_seconds,
        cleanup_interval_seconds=settings.file_cache.cleanup_interval_seconds,
        max_file_bytes=settings.file_cache.max_file_bytes,
    )
    perception_client = PerceptionClient(settings.perception)
    adapters = AdapterRegistry(tokens=settings.adapter_tokens, codec=codec, reserved_tool_names=set(), ack_timeout=settings.ack_timeout_seconds, ack_attempts=settings.ack_max_attempts, capability_timeout=settings.capability_timeout_seconds)
    builtin_tools = BuiltinTools(adapters=adapters, contexts=contexts, cache=cache, perception=FilePerceptionRouter(perception_client), memory=memory)
    adapters.set_reserved_tool_names(builtin_tools.names)
    agent = Agent(llm_client=llm, builtin_tools=builtin_tools, adapters=adapters, contexts=contexts, codec=codec, max_turns=settings.max_turns, max_retries=settings.llm_max_retries, temperature=settings.temperature, observability=observability)
    sessions = SessionManager(agent=agent, adapters=adapters, contexts=contexts, codec=codec, debounce_seconds=settings.debounce_seconds)
    adapters.set_event_handler(sessions.submit_event)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await cache.start()
        yield
        await sessions.close()
        await contexts.close()
        await cache.close()
        await perception_client.close()
        await llm.close()
        await memory_http.aclose()
        await asyncio.to_thread(observability.flush, settings.langfuse.request_timeout)

    app = FastAPI(title="core-service", version="2.0.0", lifespan=lifespan)
    app.include_router(create_router(adapters=adapters))
    app.state.adapters = adapters
    app.state.contexts = contexts
    return app
