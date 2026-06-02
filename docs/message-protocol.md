# message-protocol

## 1. 协议定位

AICHAN 全链路使用 OneBot v11 原生 JSON 格式，不做二次转换。`hub-service` 透传 OneBot v11 事件给 `agent-service`，`agent-service` 的 LLM 直接输出 OneBot v11 消息段数组作为回复。

## 2. 输入格式（事件）

hub-service 将收到的 OneBot v11 事件原样透传：

```json
[{
  "post_type": "message",
  "message_type": "private",
  "user_id": 123456,
  "message_id": 999,
  "sender": {"nickname": "小明", "card": ""},
  "message": [
    {"type": "text", "data": {"text": "你好"}},
    {"type": "image", "data": {"file": "http://..."}},
    {"type": "at", "data": {"qq": "10001"}}
  ]
}]
```

## 3. 输出格式（回复）

agent-service 的 LLM 被指示直接输出如下结构：

```json
{
  "reply": [
    {"type": "text", "data": {"text": "笨蛋，找我有什么事喵？"}}
  ],
  "auto_escape": false
}
```

### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `reply` | `list[dict]` | OneBot v11 消息段数组，与输入 `message` 字段格式一致 |
| `auto_escape` | `bool` | 是否作为纯文本发送（不解析 CQ 码），默认 `false` |

### 消息段类型

| type | data | 说明 |
|------|------|------|
| `text` | `{"text": "..."}` | 文本内容 |
| `image` | `{"file": "url或base64"}` | 图片 |
| `at` | `{"qq": "QQ号"}` | @某人 |
| `reply` | `{"id": "消息ID"}` | 回复某条消息 |

## 4. hub 透传映射

hub-service 将 agent 返回的字段直接映射到 NapCat 的 OneBot v11 动作：

```python
# agent 返回
{"reply": [...], "auto_escape": false}

# hub 发送的 OneBot v11 动作
{
  "action": "send_private_msg",
  "params": {
    "user_id": 123456,
    "message": [...],    # ← reply 直接透传
    "auto_escape": false # ← auto_escape 直接透传
  }
}
```

## 5. 兼容处理

agent-service 的 `_parse_agent_reply()` 对 LLM 输出做容错解析：

| LLM 实际输出 | 处理方式 |
|-------------|---------|
| `{"reply":[...], "auto_escape":false}` | 标准解析 |
| `{"reply":{...}, "auto_escape":false}` | 单对象自动包装为数组 |
| 纯文本字符串 | fallback：视为 `Message(text)`，`auto_escape=false` |
