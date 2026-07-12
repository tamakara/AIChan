# AICHAN XML 消息协议

## 输入

```xml
<messages>
  <message id="1" timestamp="1710000000" sender_id="u1" sender_name="小明" mentioned="true">
    <text>你好</text>
    <image object_key="sha256" name="a.png" mime_type="image/png" />
    <mention target_id="bot" />
    <quote message_id="0" />
    <extension namespace="qq" name="face">
      <param name="name">微笑</param>
    </extension>
  </message>
</messages>
```

通用节点只有 `text/image/file/audio/video/mention/quote/extension`。媒体只传 file-service 的 object_key，不允许渠道临时 URL。连续批次由 hub 合并为一个 `<messages>`。

## 输出

```xml
<reply>
  <message target_id="u1" target_name="小明" mention="true">
    <text>收到。</text>
    <extension namespace="qq" name="poke">
      <param name="target_id">u1</param>
    </extension>
  </message>
</reply>
```

最终回复根节点必须是 `<reply>`，其直接子节点只能是 `<message>`。只能引用上下文或工具结果中真实存在的 object_key。渠道扩展必须在适配器注册时声明对应方向和参数 JSON Schema；hub 在投递前校验，未知扩展会拒绝发送。

协议规则作为 `skills/system/message-protocol/SKILL.md` 注入 agent，渠道细节由当前适配器 skill 补充。
