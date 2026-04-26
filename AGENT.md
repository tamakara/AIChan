# AIChan Agent 约定

本文件是本仓库的协作规范。后续使用 Codex 时，默认以本文件为准执行。

## 文档规范

1. 子模块目录（例如 `agent-service/`）不创建 `README.md`。
2. 子模块说明统一放在根目录 `docs/` 下，命名为 `docs/<module-name>.md`。
3. 修改子模块接口、环境变量、启动方式时，必须同步更新对应 `docs/<module-name>.md`。
4. 根目录 `README.md` 仅保留项目总览和快速启动，不放子模块细节。

## 代码与配置规范

1. 环境变量命名以当前代码为准，不保留废弃别名。
2. Docker Compose 的键名与应用配置字段保持一致。
3. 新增配置时，同时更新 `.env.example` 和对应模块文档。

## 变更要求

1. 提交前至少做一次最小校验（例如 `docker compose config`）。
2. 文档变更要与代码变更同次提交，避免文档滞后。
