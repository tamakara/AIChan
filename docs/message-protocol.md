# XML Message Protocol v2

协议只区分内联文本和 Adapter 文件引用，不区分图片、音频或视频。

## 输入

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

实时输入至少包含一个 message；历史查询可以返回 `<messages />`。`id/timestamp/sender_id` 必填。输入节点只允许 `text/file/mention/quote/extension`。

## 输出

```xml
<reply>
  <message target_id="u1" mention="true">
    <text>收到。</text>
    <file ref="msg-1:file-1" name="photo.jpg" />
  </message>
</reply>
```

输出只允许 `text/file/extension`，`<reply />` 表示无需回复。最终回复只能引用实时上下文或 `message_query` 结果中出现过的 file ref。类型和 MIME 由 Adapter HTTP 响应决定，XML 禁止 `image/audio/video/object_key/mime_type`。
