# XML Message Protocol v2

## 输入

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

输入至少包含一个 message。`id/timestamp/sender_id` 必填；通用节点为 `text/image/file/audio/video/mention/quote/extension`。媒体 key 必须是 64 位小写 SHA-256。

## 输出

```xml
<reply>
  <message target_id="u1" mention="true">
    <text>收到。</text>
    <extension type="qq.poke" target_id="u1" count="2" />
  </message>
</reply>
```

`<reply />` 表示无需回复。输出只允许 `text/image/file/audio/video/extension`；mention 由 message 属性表达。Extension 参数依据在线 Manifest 的 JSON Schema 转换为 string、integer、number 或 boolean，禁止嵌套值和未知属性。

Core 使用单一安全 codec 解析、合并和序列化 XML，拒绝 DTD/ENTITY、超过 256 KiB 的 payload、未声明扩展及上下文中不存在的媒体 key。
