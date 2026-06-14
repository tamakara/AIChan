# message-protocol

## 1. 协议定位

AICHAN 在 `hub-service` 与 `agent-service` 之间使用自有 XML 协议。OneBot v11 只存在于 NapCat 接入和 QQ 动作发送边界，`hub-service` 负责把 QQ 私聊/群聊事件转换为 `<messages>`，并把 agent 的 `<reply>` 按顺序转回 OneBot v11 动作。

## 2. 输入格式

`hub-service` 在防抖窗口结束后，将同一 QQ 会话窗口内的消息合并为一个 `<messages>`。窗口级信息不重复写在每条消息里，而是在创建 agent session 时通过 `session_id=private_<user_id>|group_<group_id>` 和 `<session ... />` 系统消息提供。

```xml
<messages>
  <message id="999" time="1710000000" sub_type="friend" user_id="123" nickname="小明">
    <text>你好</text>
    <image object_key="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" name="abc.jpg" mime="image/jpeg" size="123" sha256="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" />
    <file object_key="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" name="note.txt" mime="text/plain" size="456" sha256="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" />
    <face id="123" />
    <reply id="998" />
    <record object_key="cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc" name="a.amr" mime="audio/amr" size="789" sha256="cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc" />
    <video object_key="dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd" name="a.mp4" mime="video/mp4" size="1024" sha256="dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd" />
    <at qq="10001" />
    <share url="https://..." title="标题" content="摘要" image="https://..." />
    <location lat="39.9" lon="116.3" title="位置" content="说明" />
    <contact type="qq" id="123456" />
    <unsupported type="unknown" />
  </message>
</messages>
```

`user_id` 是发言人的唯一身份标识，`nickname` 只用于称呼和展示。群聊消息会额外携带 `at_bot="true|false"`，表示该消息是否 @ 机器人。

群聊输入示例：

```xml
<messages>
  <message id="1000" time="1710000001" sub_type="normal" user_id="456" nickname="小红" at_bot="true">
    <at qq="10001" />
    <text>帮我总结一下刚才的问题</text>
  </message>
</messages>
```

媒体段规则：
- `image/record/video` 处理 OneBot message segment 中带 `url` 的内容
- `file` 若自带 `url` 则直接下载；若没有 `url`，hub-service 会优先用 NapCat `get_private_file_url` / `get_file` 根据 `file_id` 换取下载 URL
- hub-service 会把媒体临时 URL 交给 file-service 入库，XML 中只暴露 `object_key/name/mime/size/sha256`
- object_key 固定为文件 SHA-256，不包含来源、会话、消息 ID 或扩展名
- 原始 NapCat URL 不会出现在 XML 中
- 无法换取下载 URL 的文件段输出 `<unsupported type="file" name="..." />`，尽量保留文件名等安全元信息

## 3. 输出格式

LLM 最终回复必须是 `<reply>`：

```xml
<reply>
  <text>笨蛋，找我有什么事喵？</text>
  <image object_key="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" />
  <file object_key="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" />
  <face id="123" />
</reply>
```

hub-service 支持的回复节点：

| 节点 | 属性 | OneBot v11 映射 |
|------|------|-----------------|
| `text` | 文本内容 | `{"type":"text","data":{"text":"..."}}` |
| `image` | `object_key` | 从 file-service 读取 bytes，转为 `image.file=base64://...` |
| `image` | `file` | 直接透传为 `image.file`，用于外部可访问 URL |
| `file` | `object_key` | 从 file-service 读取 bytes，调用 NapCat `upload_private_file` / `upload_group_file` |
| `file` | `file` + `name` | 调用 NapCat `upload_private_file` / `upload_group_file`，用于外部可访问 URL |
| `face` | `id` | `face` 段 |
| `record` | `object_key` | 从 file-service 读取 bytes，转为 `record.file=base64://...` |
| `record` | `file` | 直接透传为 `record.file`，用于外部可访问 URL |
| `video` | `object_key` | 从 file-service 读取 bytes，转为 `video.file=base64://...` |
| `video` | `file` | 直接透传为 `video.file`，用于外部可访问 URL |

`object_key` 只能引用 `<messages>` 或工具结果里真实出现过的对象，不能编造。空 `<reply />` 不发送 QQ 消息。私聊回复对象由 hub-service 的会话路由固定决定，agent 不指定 `target_user_id`。

群聊中如果需要回复特定成员，用 `<message>` 分组承载目标用户：

```xml
<reply>
  <message target_user_id="456" target_nickname="小红" at="true">
    <text>收到，笨蛋小红，我来总结喵。</text>
  </message>
</reply>
```

`target_user_id` 必须来自上下文中真实出现过的 `user_id`。`at="true"` 时，hub-service 会在该条 OneBot 消息前插入 `at` 段。

发送规则：
- `<reply>` 的直接子节点是出站消息边界；两个 `<text>` 会发送成两条消息
- 群聊 `<message>` 分组内的子节点各自作为出站消息边界，并复用同一个 target
- `text/image/face/record/video` 每个节点各自调用一次 `send_private_msg` 或 `send_group_msg`
- `file` 节点在原始顺序位置调用 `upload_private_file` 或 `upload_group_file`
- 不支持的回复节点会被忽略

## 4. HTTP 契约

`POST /chat` 请求：

```json
{
  "session_id": "group_20001",
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
