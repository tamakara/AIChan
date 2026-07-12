---
id: aichan-message-protocol
version: "1.0"
description: AICHAN 渠道无关 XML 消息协议
enabled: true
---
用户输入使用 `<messages>`，最终回复必须使用可解析的 `<reply>`，不要输出 Markdown 代码块或自然语言前缀。

`<messages>` 下包含一个或多个 `<message>`。通用属性包括 `id`、`timestamp`、`sender_id`、`sender_name`、`mentioned`；通用子节点只有 `text`、`image`、`file`、`audio`、`video`、`mention`、`quote`、`extension`。

最终回复的 `<reply>` 下包含零个或多个 `<message>`。需要定向回复时使用 `target_id`、`target_name` 和 `mention="true"`。媒体只能引用上下文或工具结果中真实存在的 `object_key`，不能编造，也不能直接输出外部 URL。

渠道能力统一表示为 `<extension namespace="..." name="..."><param name="...">值</param></extension>`。只能使用当前适配器 skill 明确声明的扩展和参数。
