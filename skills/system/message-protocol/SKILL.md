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
    <text>你好</text>
    <image object_key="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef" name="a.png" mime_type="image/png" />
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
    <extension type="qq.poke" target_id="u1" count="2" />
  </message>
</reply>
```

输入通用节点为 `text/image/file/audio/video/mention/quote/extension`；输出只允许 `text/image/file/audio/video/extension`。渠道扩展只能使用当前 Adapter skill 声明的扁平标量属性。媒体只能引用上下文或工具结果中真实存在的 `object_key`。无需回复时输出 `<reply />`。
