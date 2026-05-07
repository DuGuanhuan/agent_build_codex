# Runtime Protocol v1

本文档定义当前项目内 Handmade、OpenCode、Claude Code 共同遵守的最小协议。目标是让前端只消费一套事件、产物和 Turn 结构，后续接入 OpenClaw、Gemini CLI、Codex CLI 时不再新增 runtime 专属主逻辑。

## 1. RuntimeEvent

所有 runtime 对外输出的 SSE payload 都带：

| 字段 | 说明 |
| --- | --- |
| `protocol_version` | 固定为 `runtime-event.v1` |
| `event` | 事件名 |
| `event_id` | 单个事件唯一 ID |
| `sequence` | 单次 runtime 调用内递增序号 |
| `created_at` | 服务端事件生成时间戳 |
| `runtime` | `handmade` / `opencode` / `claude-code` |
| `trace_id` | 当前 assistant turn 的追踪 ID |
| `turn_id` | WorkBuddy 自己的 Turn ID |

当前事件名：

| 事件 | 说明 |
| --- | --- |
| `message_start` | assistant turn 开始 |
| `text_delta` | 最终回答文本增量 |
| `tool_start` | 工具开始，或工具等待确认 |
| `tool_result` | 工具成功 |
| `tool_error` | 工具失败 |
| `artifact_updated` | 产物更新 |
| `session_diff` | diff 产物更新 |
| `session_todo` | todo/plan 产物更新 |
| `session_status` | runtime session 状态变化 |
| `message_done` | assistant turn 完成 |
| `error` | runtime 或服务端错误 |

兼容规则：

- 旧事件 `tool_awaiting_approval` 会归一成 `tool_start`，并通过 `status=awaiting_approval` 表达等待用户确认。
- 前端不应依赖 OpenCode 或 Claude Code 的原始字段作为必填字段。
- runtime 专属数据必须放在 `artifact.data`、`step.result` 或未来的 `raw` 字段里。

## 2. ToolStep

工具事件和 `message_done.steps[]` 使用同一结构：

| 字段 | 说明 |
| --- | --- |
| `id` | 工具调用 ID |
| `type` | `tool` / `tool_error` 或扩展值 |
| `status` | `running` / `success` / `error` / `awaiting_approval` 等 |
| `tool` | 工具名 |
| `args` | 工具参数 |
| `result` | 工具结果 |
| `error` | 错误信息 |
| `permission` | 权限来源或审批类型 |
| `started_at` | 开始时间 |
| `ended_at` | 结束时间 |
| `duration_ms` | 执行耗时 |
| `runtime` | runtime ID |
| `trace_id` | 当前 trace |

## 3. RuntimeArtifact

所有 runtime 产物都带：

| 字段 | 说明 |
| --- | --- |
| `protocol_version` | 固定为 `runtime-artifact.v1` |
| `id` | 产物 ID |
| `type` | `file_diff` / `todo` / `diagnostic` / `trace` 等 |
| `runtime` | runtime ID |
| `title` | 前端显示标题 |
| `status` | `ready` / `running` / `error` |
| `data` | 产物内容 |
| `updated_at` | 更新时间 |

当前核心产物：

- `file_diff`：文件变更 diff。
- `todo`：runtime 内部计划、任务列表。
- `diagnostic`：adapter 无法加载 diff/todo 时的错误说明。

## 4. Turn

Turn 是 WorkBuddy 自己的可回滚执行单元，不等同于前端 message，也不等同于外部 runtime session。

所有 Turn 记录都带：

| 字段 | 说明 |
| --- | --- |
| `protocol_version` | 固定为 `runtime-turn.v1` |
| `turn_id` | WorkBuddy Turn ID |
| `session_id` | 前端会话 ID |
| `runtime_id` | 本轮使用的 runtime |
| `model_id` | 本轮请求模型 |
| `status` | `running` / `done` / `rolled_back` 等 |
| `side_effect_level` | 副作用级别 |
| `file_changes` | 可回滚文件变更 |
| `artifacts` | 本轮归档产物 |
| `event_count` | 本轮事件数量 |
| `assistant_message_id` | 前端 assistant message ID |
| `trace_id` | runtime trace |
| `error` | 错误信息 |
| `retry_of_turn_id` | 如果是重试，指向原 Turn |

## 5. 接入新 Runtime 的要求

新 runtime adapter 必须：

1. 使用 `RuntimeEventStream` 包装自己的 `event_sink`。
2. 输出 `message_start`、`text_delta`、`message_done`。
3. 工具调用统一输出 `tool_start`、`tool_result`、`tool_error`。
4. diff/todo/trace 等统一输出为 `RuntimeArtifact`。
5. 支持不了的能力要通过 `capabilities` 标记为 `false`，或返回清晰 `error`。
6. 单测必须覆盖事件翻译，不依赖真实外部 runtime。
