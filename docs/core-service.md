# core-service

core-service 负责 Adapter 长连接、消息防抖、ContextManager、Agent、按需文件缓存和所有模型工具。外部只公开 `/healthz`、`/readyz`、`/api/v2/adapters/ws` 与 Adapter 状态。

## 内置工具

- `file_perceive(file_ref, question?, max_chars?)`：从当前 Adapter 按需获取文件，按 MIME 路由文本、图片、音频、视频或 binary。
- `message_query(cursor?, limit?)`：只查询当前会话的渠道历史，结果中的 file ref 自动加入上下文。
- `memory_get_user_memory(user_id, start_line?, line_count?)`：直接读取 memory-service 用户长期记忆。
- `adapter__*`：当前 Adapter Manifest 声明的可选 capability。

## 文件缓存

缓存默认位于 `/tmp/aichan-file-cache`，TTL 3600 秒、清理间隔 600 秒、单文件上限 10 MiB。相同 Adapter/file ref 使用 single-flight。缓存不挂载 volume，不承担永久保存、生成文件托管或跨 Adapter 分享。

感知配置使用 `CORE__PERCEPTION__*`，图片和视频共享 visual model，音频使用独立 audio transcription model。Core 优先使用 Adapter 的 `Content-Type`，通用二进制类型再按文件名后缀推断；未知二进制只返回文件名、MIME、大小和 `supported=false`。

## 上下文与记忆

每轮上下文按 system.md、本地 skills、当前 Adapter skills、session XML、最后成功 memory、历史和暂存消息生成。未压缩记录保存在内存，达到阈值后异步写入 memory-service；消息渠道原始历史通过 `message_query` 获取。
