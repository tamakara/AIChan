---
id: qq-channel
version: "1.0"
description: QQ 消息语义、查询能力和特殊动作
enabled: true
---
当前会话来自 QQ。需要查询用户资料时调用 `adapter_invoke`，capability 使用 `user.get`，arguments 为 `{"user_id": "..."}`；查询历史消息使用 `message.history`，arguments 包含 `message_type`、`peer_id`、`limit` 和可选 `before_message_id`。

QQ 表情输入为 `<extension namespace="qq" name="face"><param name="name">微笑</param></extension>`，商城表情为 `mface` 扩展，可根据 summary 理解语气。

回复中可使用 `face` 扩展，name 必须来自输入中出现过的名称或常见 QQ 表情名称。戳一戳使用：
`<extension namespace="qq" name="poke"><param name="target_id">真实用户 ID</param></extension>`。
target_id 必须来自当前上下文，不能猜测。
