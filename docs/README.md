# 文档索引

## 推荐阅读顺序
1. [aichan.md](aichan.md) - 先建立系统级认知，理解三服务如何拼接成闭环。
2. [message-protocol.md](message-protocol.md) - 再看统一内部消息 XML 协议，明确跨服务消息契约。
3. [adapter-service.md](adapter-service.md) - 接着看消息入口与回写边界，理解事件和动作如何流转。
4. [hub-service.md](hub-service.md) - 了解中枢如何消费事件、做防抖并触发 agent。
5. [agent-service.md](agent-service.md) - 最后看推理与工具调用层，补齐 LLM 回合状态机。

## 模块简介
- `aichan.md`：系统总览、链路图、部署拓扑与跨服务边界。
- `message-protocol.md`：统一内部消息 XML 协议与 NapCat 映射规则。
- `adapter-service.md`：OneBot 接入、Redis 事件/动作流、MCP 历史查询。
- `hub-service.md`：事件消费、防抖合并、调用 `agent-service`、写回动作流。
- `agent-service.md`：会话上下文、LLM 推理、多轮工具调用与 `/chat`。

