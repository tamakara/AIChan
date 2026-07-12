# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

使用中文回复。

## What this is

AICHAN is a QQ private/group chat assistant built on NapCat + OneBot v11, an LLM, and MCP tools. It is split into five independent Python services orchestrated by Docker Compose, plus NapCat and a Docker MCP Gateway. The overall boundary: `hub-service` owns the single NapCat WebSocket, `file-service` owns MinIO, `memory-service` owns persisted memory, and `agent-service` only deals with AICHAN XML, model context, and the tool loop.

## Repository layout

This is a `uv` workspace (`pyproject.toml` `[tool.uv.workspace]`). Each member is a self-contained FastAPI service with the same shape:

```
<service>/
  src/<package>/
    main.py        # uvicorn entrypoint (project.scripts)
    app.py         # FastAPI app factory
    config.py      # pydantic-settings Settings + get_settings()
    logger.py
    router/        # HTTP routes + request/response schemas
    services/      # domain logic
  tests/
  config.yml       # non-secret config, mounted read-only into the container
  Dockerfile
  pyproject.toml
```

Members: `agent-service`, `hub-service`, `memory-service`, `file-service`, `skill-service`, `tool-mcp-server`. Channel adapters are **not** workspace members — they are self-contained repos with their own Compose. The bundled QQ/NapCat adapter lives under `adapters/aichan-qq-adapter/` and is meant to be extracted to its own repository.

## Commands

The core services and each channel adapter are split across separate Compose files. They share one network (`aichan-adapter-network`) that the **core** Compose owns and the adapter references as `external`, so the core must start first.

Step 1 — core services (build + start all core services, MinIO, MCP Gateway; also creates the shared network):

```bash
docker compose up -d --build
docker compose logs -f hub-service agent-service memory-service file-service skill-service tool-mcp-server
```

Step 2 — QQ adapter + NapCat (from the adapter directory, whose Compose context is the adapter itself):

```bash
cd adapters/aichan-qq-adapter && docker compose up -d --build
```

Before first run, copy `.env.example` to `.env` and fill in at least the agent and memory model names + API keys, plus a matching adapter token (`HUB__ADAPTER_TOKENS` for `qq:main` on the core side, `ADAPTER__HUB_TOKEN` in `adapters/aichan-qq-adapter/.env` on the adapter side). NapCat login is at http://localhost:6099/webui (token in `adapters/aichan-qq-adapter/napcat/config/webui.json`).

Tests are per-service. Each service declares its test deps in an optional `test` extra, so run pytest through `uv run` from inside the service directory:

```bash
cd agent-service && uv run --extra test pytest -q          # all tests for one service
cd agent-service && uv run --extra test pytest tests/test_agent.py -q          # single file
cd agent-service && uv run --extra test pytest tests/test_agent.py::test_name  # single test
```

There is no repo-wide test runner or lint config — iterate service by service.

## Configuration model

Every service loads config through `pydantic-settings` with this precedence (highest first): explicit init args > environment variables > root `.env` > `<service>/config.yml`. Env vars use nested delimiter `__`, e.g. `AGENT__MODEL` maps to `agent.model`, `AGENT__LANGFUSE__HOST` maps to `agent.langfuse.host`.

- `config.yml` holds non-secret defaults and empty placeholders. Secrets (model names, API keys, MinIO creds, vision keys) come from `.env` and are injected by `docker-compose.yml` per service. `.env` is gitignored; only `.env.example` is committed.
- `CONFIG_PATH` in each `config.py` is resolved relative to `Path.cwd()` (e.g. `Path.cwd() / "agent-service" / "config.yml"`), so services expect to be launched from the repo root inside the container. Tests monkeypatch `CONFIG_PATH`, so they are CWD-independent.
- Settings models use `extra="forbid"` and `Strict*` types — adding a config key requires updating both `config.yml` and the pydantic model. In YAML, `key:` parses as `null` and `key: ""` as empty string; required secrets reject both.

## Ports

Host ports are shifted to avoid Windows reserved ranges; container-internal ports are unchanged, so inter-service URLs in `config.yml` keep the original ports.

| Service | Container | Host |
|---|---|---|
| agent-service | 8000 | 18000 |
| hub-service | 8020 | 18020 |
| tool-mcp-server | 8030 | (internal only) |
| file-service | 8040 | 18040 |
| memory-service | 8050 | 18050 |
| mcp-gateway | 9000 | 19000 |
| minio console | 9001 | 19001 |
| napcat webui | 6099 | 6099 |

## Message flow (the core architecture)

A QQ message travels: QQ user → NapCat (OneBot v11) → `hub-service` → `agent-service` → back to QQ. The key architectural decision is a **private AICHAN XML protocol** between hub and agent, so the agent never sees raw OneBot v11 fields and hub never sees model-vendor message structures. See [docs/message-protocol.md](docs/message-protocol.md).

- `hub-service` receives OneBot v11 events over one reverse WebSocket, applies the session whitelist, debounces/merges messages per `session_id`, converts them to `<messages>` XML, and calls the agent. It converts the agent's `<reply>` XML back into OneBot actions and sends them over the same WS. `session_id` is `private_<user_id>` or `group_<group_id>`.
- Media is never passed as URLs through the protocol. `hub-service` sends NapCat temp URLs to `file-service`, which stores the bytes in MinIO keyed by content SHA-256 and returns an `object_key`. Only `object_key` + `name` appear in XML. The agent must call MCP tools (`image_describe`, `video_describe`, `file_read_text`) to learn media contents — it must never guess from filenames.
- `agent-service` runs a turn loop: refresh memory → stage messages → call LLM → either execute MCP tool calls or accept a final `<reply>`. Staged messages commit only on a valid final reply. New messages arriving mid-run go to `/sessions/{id}/queue-message` and are absorbed at turn boundaries (possibly abandoning an unsent reply). Only a parseable `<reply>` root is accepted; invalid XML retries within `llm_max_retries`, then falls back to a fixed reply. See [docs/agent-service.md](docs/agent-service.md).
- `memory-service` keeps two memory layers: per-`session_id` lossless compressed logs (agent reads before each run, compresses in a background thread past a record threshold) and per-`user_id` internalized profiles (async, fetched on demand via the `memory_get_user_memory` MCP tool). Memory failures degrade gracefully and never block chat.
- `tool-mcp-server` adapts domain HTTP APIs into MCP tools; it holds no NapCat WS or MinIO creds and reaches hub/file/memory over HTTP. It is exposed to the agent through the Docker MCP Gateway (which also aggregates Tavily and time tools).

Session state for both `hub-service` and `agent-service` lives in process memory — single-instance deployment, lost on restart.

## Documentation discipline (from AGENTS.md)

These project conventions are mandatory and enforced across the codebase:

- **No backward-compat code.** When updating or refactoring a feature, overwrite the old design directly. Do not write compatibility shims, migration scripts, or keep deprecated interfaces/env-var aliases. Environment variable names track the latest code with zero redundancy.
- **Comments explain *why*.** Complex code (core algorithms, cross-service interactions, workarounds) must carry Chinese comments explaining business intent and boundary conditions, not restating what the syntax does.
- **Docs are centralized in `docs/`.** The root `README.md` must not contain sub-module detail, and sub-module directories must never contain their own `README.md`. All per-module docs live at `docs/<module-name>.md`. After any code change, the final step is to check and update the matching `docs/<module-name>.md` — especially when an interface, environment variable, or startup method changes.
- **Minimal exception handling.** Do not add fine-grained `except` branches (e.g. per network-error type) unless explicitly asked. Keep `try/except` only at service/flow boundaries (entry routes, async task boundaries, cross-service call wrappers). Match `agent-service`'s minimal style across services; errors are logged only at the outermost router layer while inner layers raise directly.

The `docs/onebot-11/` submodule is external OneBot v11 reference only — internal contracts are defined by `docs/message-protocol.md` and the service docs, not by it.
