# message-protocol

## 1. 协议定位

AICHAN 在 `hub-service` 与 `agent-service` 之间使用自有 XML 协议。OneBot v11 只存在于 NapCat 接入和 QQ 动作发送边界，`hub-service` 负责把 QQ 私聊事件转换为 `<messages>`，并把 agent 的 `<reply>` 转回 OneBot v11 私聊消息段。

## 2. 输入格式

`hub-service` 在防抖窗口结束后，将同一 QQ 私聊会话内的消息合并为一个 `<messages>`：

```xml
<messages>
  <message id="999" time="1710000000" sub_type="friend" nickname="小明">
    <text>你好</text>
    <image file="abc.jpg" url="https://..." type="flash" />
    <face id="123" />
    <reply id="998" />
    <record file="a.amr" url="https://..." />
    <video file="a.mp4" url="https://..." />
    <at qq="10001" />
    <share url="https://..." title="标题" content="摘要" image="https://..." />
    <location lat="39.9" lon="116.3" title="位置" content="说明" />
    <contact type="qq" id="123456" />
    <unsupported type="unknown" />
  </message>
</messages>
```

`user_id`、`self_id` 等稳定身份信息不写入每条消息，而是在创建 agent session 时通过 metadata 写入 `<session_info>` 系统消息。

## 3. 输出格式

LLM 最终回复必须是 `<reply>`：

```xml
<reply>
  <text>笨蛋，找我有什么事喵？</text>
  <image file="https://..." />
  <face id="123" />
</reply>
```

hub-service 支持的回复节点：

| 节点 | 属性 | OneBot v11 映射 |
|------|------|-----------------|
| `text` | 文本内容 | `{"type":"text","data":{"text":"..."}}` |
| `image` | `file` | `image` 段 |
| `face` | `id` | `face` 段 |
| `record` | `file` | `record` 段 |
| `video` | `file` | `video` 段 |

空 `<reply />` 不发送 QQ 消息。私聊回复对象由 hub-service 的会话路由固定决定，agent 不指定 `user_id`。

## 4. HTTP 契约

`POST /chat` 请求：

```json
{
  "session_id": "uuid",
  "input_xml": "<messages>...</messages>"
}
```

响应：

```json
{
  "output_xml": "<reply><text>...</text></reply>"
}
```

## 5. 容错处理

agent-service 只接受最终 `<reply>` 作为标准输出。LLM 若返回非法 XML 或非 `<reply>` 根节点，agent-service 会将原始内容包装为：

```xml
<reply><text>原始内容</text></reply>
```
