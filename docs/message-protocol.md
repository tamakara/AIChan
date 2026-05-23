# message-protocol

## 1. 文档目的
本文定义 AICHAN 统一内部消息 XML 协议（当前草案）。  
目标是把 NapCat / OneBot v11 的消息在 `adapter-service` 一次性规范化，后续 `hub-service` 与 `agent-service` 只消费协议结果，不再重复做字段拼装。

当前状态：
- 协议草案已确定（本文档）。
- `adapter-service` / `hub-service` / `agent-service` 主链路已切换到本协议。
- 当前代码实现已支持 `message` / `poke` / `recall` 事件标签与 `<batch type="start|append">` 批次输入。

## 2. 设计结论（本次收口）
- 去掉 XML 内的 `protocol="aichan.message.xml"` 与 `version="1"` 属性。
- 把批次容器从 `<messages>` 统一改名为 `<batch>`。
- `adapter-service` 只负责单条事件标签（`<message>` / `<poke>` / `<recall>`）规范化。
- `hub-service` 按现有会话调度策略，把多条事件标签组合成 `<batch type="...">`。
- `<batch type="...">` 中的 `type` 语义等价于旧版 `messages.mode`（`start|append`）。

## 3. 分层职责
- `adapter-service`
  - 唯一负责：`OneBot 事件 -> 单条 event XML`
  - 负责文本清洗、字段归一、XML 转义
- `hub-service`
  - 只做会话调度、防抖、重跑决策
  - 负责把单条 `event XML` 组合成批次 `batch XML`
- `agent-service`
  - 只把 `batch XML` 当作输入上下文消费
  - 不再负责消息标签拼装与 XML 转义

## 4. 单条事件 XML（Message / Notice）
### 4.1 `message` 标准结构
```xml
<message
  message_type="private"
  sub_type="friend"
  message_id="123456789"
  session_id="private_123456"
  user_id="qq_123456"
  time="1710000000"
>你好</message>
```

### 4.2 `message` 字段约束
- `message_type`：`private | group`
- `sub_type`：透传 OneBot v11 `sub_type`
  - `message_type=private`：常见为 `friend | group | other`
  - `message_type=group`：常见为 `normal | anonymous | notice`
- `message_id`：透传 OneBot v11 `message_id`（建议按字符串写入 XML 属性）
- `session_id`：
  - 私聊：`private_<user_id>`
  - 群聊：`group_<group_id>`
- `user_id`：固定 `qq_<onebot_user_id>`
- `time`：必须来自 `raw_event.time`，秒级时间戳字符串
- 文本内容：
  - 先执行 `extract_plain_text`
  - 再移除残留 CQ 码并 `strip()`
  - 清洗后为空则整条事件丢弃，不入流

### 4.3 `poke` 标准结构（Notice Event）
```xml
<poke session_id="group_987654321" user_id="qq_123456" target_id="qq_654321" />
```

字段约束：
- `session_id`：会话路由键（`private_*` 或 `group_*`）
- `user_id`：发起戳一戳的用户，统一为 `qq_<onebot_user_id>`
- `target_id`：被戳用户，统一为 `qq_<onebot_target_id>`

### 4.4 `recall` 标准结构（Notice Event）
```xml
<recall session_id="group_987654321" user_id="qq_123456" message_id="123456789" />
```

字段约束：
- `session_id`：会话路由键（`private_*` 或 `group_*`）
- `user_id`：撤回动作相关用户（按 OneBot 事件字段映射）
- `message_id`：被撤回消息的 ID（建议按字符串写入 XML 属性）

## 5. 批次容器 XML（Batch）
### 5.1 标准结构
```xml
<batch type="start">
  <message message_type="private" sub_type="friend" message_id="123456789" session_id="private_123456" user_id="qq_123456" time="1710000000">第一条</message>
  <poke session_id="private_123456" user_id="qq_123456" target_id="qq_654321" />
  <recall session_id="private_123456" user_id="qq_123456" message_id="123456790" />
</batch>
```

### 5.2 `batch.type` 语义
- `start`：当前回复链路的首轮输入
- `append`：同一回复链路中，因新消息到达触发的覆盖式重跑输入

约束：
- 同一个 `<batch>` 内所有事件标签（`message/poke/recall`）必须来自同一 `session_id`
- 事件顺序必须与原始到达顺序一致

## 6. Stream 字段建议（落地目标）
`qq.events` 的事件字段建议收口为：
- `event_id`
- `session_id`
- `event_xml`（单条 `<message ...>` / `<poke ... />` / `<recall ... />`）
- `raw_event`
- `created_at`

说明：
- `event_xml` 是跨服务唯一消费正文，`content` 纯文本字段可移除。
- `raw_event` 保留用于审计与诊断，不参与下游协议拼装。

## 7. NapCat -> 协议映射规则
- NapCat `private` 消息：
  - `message.message_type=private`
  - `message.sub_type=<onebot_private_sub_type>`
  - `message.message_id=<onebot_message_id>`
  - `message.session_id=private_<user_id>`
- NapCat `group` 消息：
  - `message.message_type=group`
  - `message.sub_type=<onebot_group_sub_type>`
  - `message.message_id=<onebot_message_id>`
  - `message.session_id=group_<group_id>`
- `message.time`：只取 `raw_event.time`
- `message.user_id`：统一转为 `qq_<user_id>`

- NapCat `notice.notify.poke`：
  - 生成 `<poke ... />`
  - `poke.session_id=<private_* 或 group_*>`
  - `poke.user_id=qq_<user_id>`
  - `poke.target_id=qq_<target_id>`

- NapCat `notice.*_recall`：
  - 生成 `<recall ... />`
  - `recall.session_id=<private_* 或 group_*>`
  - `recall.user_id=qq_<user_id>`
  - `recall.message_id=<message_id>`

## 8. 落地步骤（建议）
1. `adapter-service` 增加 `event_xml` 生成器并写入 `qq.events`。
2. `hub-service` 改为透传 `event_xml`，仅决定 `batch.type=start|append` 并构造 `<batch>` 容器。
3. `agent-service` 删除消息 XML 构建逻辑，直接消费 hub 传入的协议 XML。
4. 同步更新 `docs/adapter-service.md`、`docs/hub-service.md`、`docs/agent-service.md` 的接口定义与示例。
