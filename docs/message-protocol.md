# message-protocol

## 1. 协议定位

AICHAN 在 `hub-service` 与 `agent-service` 之间使用自有 XML 协议。OneBot v11 只存在于 NapCat 接入和 QQ 动作发送边界，`hub-service` 负责把 QQ 私聊事件转换为 `<messages>`，并把 agent 的 `<reply>` 转回 OneBot v11 私聊消息段。

## 2. 输入格式

`hub-service` 在防抖窗口结束后，将同一 QQ 私聊会话内的消息合并为一个 `<messages>`：

```xml
<messages>
  <message id="999" time="1710000000" sub_type="friend" nickname="小明">
    <text>你好</text>
    <image object_key="qq/private/123/999/1-abc.jpg" name="abc.jpg" mime="image/jpeg" size="123" sha256="abc" />
    <file object_key="qq/private/123/999/2-def.txt" name="note.txt" mime="text/plain" size="456" sha256="def" />
    <face id="123" />
    <reply id="998" />
    <record object_key="qq/private/123/999/5-ghi.amr" name="a.amr" mime="audio/amr" size="789" sha256="ghi" />
    <video object_key="qq/private/123/999/6-jkl.mp4" name="a.mp4" mime="video/mp4" size="1024" sha256="jkl" />
    <at qq="10001" />
    <share url="https://..." title="标题" content="摘要" image="https://..." />
    <location lat="39.9" lon="116.3" title="位置" content="说明" />
    <contact type="qq" id="123456" />
    <unsupported type="unknown" />
  </message>
</messages>
```

`user_id`、`self_id` 等稳定身份信息不写入每条消息，而是在创建 agent session 时通过 metadata 写入 `<session_info>` 系统消息。

媒体段规则：
- `image/record/video` 处理 OneBot message segment 中带 `url` 的内容
- `file` 若自带 `url` 则直接下载；若没有 `url`，hub-service 会优先用 NapCat `get_private_file_url` / `get_file` 根据 `file_id` 换取下载 URL
- hub-service 会先下载媒体并写入私有 MinIO，XML 中只暴露 `object_key/name/mime/size/sha256`
- object key 固定格式：`qq/private/{user_id}/{message_id}/{segment_index}-{sha256}.{ext}`
- 原始 NapCat URL 不会出现在 XML 中
- 无法换取下载 URL 的文件段输出 `<unsupported type="file" name="..." />`，尽量保留文件名等安全元信息

## 3. 输出格式

LLM 最终回复必须是 `<reply>`：

```xml
<reply>
  <text>笨蛋，找我有什么事喵？</text>
  <image object_key="qq/private/123/999/1-abc.jpg" />
  <file object_key="qq/private/123/999/2-def.txt" />
  <face id="123" />
</reply>
```

hub-service 支持的回复节点：

| 节点 | 属性 | OneBot v11 映射 |
|------|------|-----------------|
| `text` | 文本内容 | `{"type":"text","data":{"text":"..."}}` |
| `image` | `object_key` | 从 MinIO 读取 bytes，转为 `image.file=base64://...` |
| `image` | `file` | 直接透传为 `image.file`，用于外部可访问 URL |
| `file` | `object_key` | 从 MinIO 读取 bytes，调用 NapCat `upload_private_file` |
| `file` | `file` + `name` | 调用 NapCat `upload_private_file`，用于外部可访问 URL |
| `face` | `id` | `face` 段 |
| `record` | `object_key` | 从 MinIO 读取 bytes，转为 `record.file=base64://...` |
| `record` | `file` | 直接透传为 `record.file`，用于外部可访问 URL |
| `video` | `object_key` | 从 MinIO 读取 bytes，转为 `video.file=base64://...` |
| `video` | `file` | 直接透传为 `video.file`，用于外部可访问 URL |

`object_key` 只能引用 `<messages>` 或工具结果里真实出现过的对象，不能编造。空 `<reply />` 不发送 QQ 消息。私聊回复对象由 hub-service 的会话路由固定决定，agent 不指定 `user_id`。

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
