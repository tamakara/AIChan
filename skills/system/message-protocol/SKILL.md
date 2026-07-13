---
id: aichan-message-protocol
version: "2.0"
description: AICHAN XML v2 消息协议
enabled: true
---
用户输入使用 `<messages>`，最终回复必须使用可解析的 `<reply>`，不得输出 Markdown 代码块或自然语言前缀。

输入示例：

```xml
<messages>
  <message id="1" timestamp="1710000000" sender_id="u1" sender_name="小明" mentioned="true">
    <text>帮我看看这个文件</text>
    <file ref="msg-1:file-1" name="photo.jpg" />
    <mention target_id="bot" />
    <quote message_id="0" />
  </message>
</messages>
```

输出示例：

```xml
<reply>
  <message target_id="u1" target_name="小明" mention="true">
    <text>收到。</text>
    <file ref="msg-1:file-1" name="photo.jpg" />
    <extension type="qq.poke" target_id="u1" count="2" />
  </message>
</reply>
```

输入通用节点为 `text/file/mention/quote/extension`；输出只允许 `text/file/extension`。文件类型由 `file_perceive` 根据 Adapter 返回的 MIME 判断，协议中不区分图片、音频或视频。只能引用当前上下文或 `message_query` 结果中真实存在的 file ref。无需回复时输出 `<reply />`。
