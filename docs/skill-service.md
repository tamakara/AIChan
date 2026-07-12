# skill-service

skill-service 是 runtime skill 的唯一注册与解析服务。

- 系统 skill：启动时读取 `skills/system/<id>/SKILL.md`。
- 适配器 skill：适配器注册后由 hub 整批写入内存，断线时停用。
- skill 文件使用 YAML frontmatter，字段为 `id/version/description/enabled`，正文是注入 agent 的内容。

内部接口：

- `PUT /api/v1/adapters/skills`：替换适配器实例快照。
- `DELETE /api/v1/adapters/{adapter_id}/{instance_id}/skills`：停用快照。
- `POST /api/v1/skills/resolve`：解析系统与指定适配器 skill。
- `GET /healthz`。

首版没有数据库和人工管理 API。agent 创建会话时必须成功解析一次；后续每轮刷新，skill-service 短暂失败时使用该会话最后一次成功快照。
