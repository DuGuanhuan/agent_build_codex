# Agent Runtime 切换专项 PRD

## 1. 背景

当前项目已经具备一套可用的手写 Agent 链路：Next.js 聊天前端、Python 后端、模型切换、SSE 流式输出、工具 registry、工具审批、技能系统、会话和上下文压缩。

随着项目继续迭代，后续可能希望接入更成熟的底层 Agent 能力，例如 OpenCode、Hermes、OpenClaw 等。它们可能在 coding agent、长期记忆、本地自动化、工具编排、安全策略等方面比当前手写 Agent 更强。

本需求的核心不是“替换当前 Agent”，而是让同一套前端页面可以切换不同底层 Agent Runtime，让当前手写 Agent 和外部成熟 Agent 共存、可比较、可逐步迁移。

## 2. 目标

- 在同一套聊天前端中支持切换底层 Agent Runtime。
- 保留当前模型选择、会话、上下文、流式回答和工具步骤展示体验。
- 后端建立统一 Runtime Adapter 层，屏蔽不同 Agent 框架的调用差异。
- 优先让当前 `handmade` Agent 成为第一个 Runtime，保证现有能力不退化。
- 为后续接入 OpenCode / Hermes / OpenClaw 预留稳定协议和安全边界。

## 3. 非目标

- 不在第一阶段完整接入所有第三方 Agent。
- 不让前端直接调用第三方 Agent CLI/API。
- 不要求不同 Runtime 共用完全相同的内部工具实现。
- 不在第一阶段做多用户、多租户、云端权限管理。
- 不开放第三方 Agent 访问 VPS 全盘文件或宿主机敏感目录。

## 4. 用户故事

### 4.1 作为项目使用者

我希望在聊天页面选择“底层 Agent”，例如：

```text
Handmade Agent
OpenCode
Hermes
OpenClaw
```

这样我可以在不换前端页面的情况下，比较不同 Agent 的能力和效果。

### 4.2 作为开发者

我希望新增一个 Runtime 时，只需要在后端写一个 adapter，而不需要重写前端聊天页面、会话列表、工具步骤 UI 和模型选择器。

### 4.3 作为维护者

我希望每个 Runtime 都有明确的能力声明和安全边界，例如是否支持文件编辑、shell、长期记忆、工具审批、workspace 限制。

## 5. 核心概念

### 5.1 Model Provider

模型供应商或具体模型，例如：

```text
DeepSeek V4 Flash
MiMo V2.5
智谱 GLM-4.7-Flash
万擎 Kimi K2.5
```

模型回答“用哪个大模型生成”。

### 5.2 Agent Runtime

底层 Agent 架构或执行器，例如：

```text
handmade
opencode
hermes
openclaw
```

Runtime 回答“由哪套 Agent 编排、工具执行和上下文机制来完成任务”。

### 5.3 Runtime Adapter

后端用于把不同 Runtime 统一成当前产品协议的一层适配器。

前端只理解统一事件：

```text
message_start
text_delta
tool_start
tool_result
tool_error
tool_awaiting_approval
message_done
error
```

每个 Runtime Adapter 负责把自己的运行过程翻译成这套事件。

## 6. 产品方案

### 6.1 前端入口

在聊天页面增加 Agent Runtime 选择能力。

推荐方案：

- 模型选择器继续用于选择 LLM 模型。
- Runtime 选择器放在模型选择器附近，但视觉权重更低。
- 每个会话保存独立 `runtimeId` 和 `modelId`。
- 切换会话时恢复该会话的 Runtime 和模型。

示例：

```text
Agent: Handmade Agent v1
Model: DeepSeek V4 Flash
```

或：

```text
Agent: OpenCode
Model: MiMo V2.5
```

### 6.2 Runtime 列表

新增接口：

```text
GET /api/runtimes
```

返回：

```json
{
  "runtimes": [
    {
      "id": "handmade",
      "label": "Handmade Agent",
      "description": "当前项目内置的轻量手写 Agent。",
      "available": true,
      "default": true,
      "capabilities": {
        "chat": true,
        "stream": true,
        "tools": true,
        "tool_approval": true,
        "file_read": true,
        "file_write": true,
        "shell": true,
        "skills": true,
        "memory": "local_summary",
        "workspace_scope": "project"
      }
    }
  ],
  "default": "handmade"
}
```

### 6.3 聊天请求

现有接口继续复用：

```text
POST /api/chat/stream
```

请求增加 `runtime` 字段：

```json
{
  "runtime": "handmade",
  "model": "deepseek-v4-flash",
  "messages": [
    { "role": "user", "content": "帮我看看这个项目结构" }
  ],
  "trusted_tools": []
}
```

如果不传 `runtime`，默认使用：

```text
handmade
```

### 6.4 会话持久化

`ChatSession` 增加字段：

```ts
type ChatSession = {
  runtimeId: string;
  modelId: string;
  messages: DisplayMessage[];
  ...
}
```

localStorage 继续使用现有 key：

```text
agent:sessions
agent:active-session-id
agent:model
```

可新增：

```text
agent:runtime
```

### 6.5 消息展示

每条 assistant 消息下方显示：

```text
使用 Agent：Handmade Agent
使用模型：DeepSeek V4 Flash
```

如果 Runtime Adapter 能返回更具体的执行器版本，也可以展示：

```text
使用 Agent：OpenCode 1.x
```

### 6.6 Runtime 能力标签

前端展示 runtime 时可以显示能力标签：

```text
聊天
流式
工具
文件编辑
Shell
长期记忆
需要沙箱
实验性
```

第一阶段只展示少量关键标签：

```text
内置
支持工具
支持审批
项目工作区
实验性
```

## 7. Runtime 分期规划

### Phase 1：Runtime 抽象和 Handmade 迁移

目标：不接第三方，先把当前手写 Agent 包成 Runtime。

范围：

- 新增 `GET /api/runtimes`。
- 新增后端 runtime registry。
- 将当前 `run_agent` 封装为 `handmade` runtime。
- `/api/chat` 和 `/api/chat/stream` 支持 `runtime` 字段。
- 前端新增 runtime 选择器。
- 会话保存 `runtimeId`。

验收：

- 默认 runtime 是 `handmade`。
- 不传 runtime 时现有聊天能力不退化。
- 选择 `handmade` 后聊天、工具调用、审批、摘要仍可用。
- 刷新页面后恢复当前会话 runtime。

### Phase 2：接入 OpenCode Adapter

目标：接入第一个外部 coding agent runtime。

推荐优先接 OpenCode，因为它和当前项目的 coding agent 方向最接近：文件读取、代码修改、shell、终端工作流。

范围：

- 在后端增加 `opencode` runtime adapter。
- 明确 OpenCode 的运行方式：CLI、子进程或本地服务。
- 将 OpenCode 输出翻译成统一 SSE 事件。
- 限制 OpenCode 工作目录为项目 workspace。
- 高风险操作接入现有审批机制，或者明确标记为 adapter 内部审批。

验收：

- 前端可选择 `OpenCode`。
- OpenCode 能完成一次项目内只读分析任务。
- OpenCode 能返回流式文本。
- 如果执行文件写入或 shell，前端能看到可理解的工具步骤或审批提示。
- OpenCode 不可访问 `.env.production`、`.ssh`、VPS home 等敏感路径。

### Phase 3：评估 Hermes / OpenClaw

目标：决定是否接入更宽能力面的 Agent。

Hermes 关注点：

- 是否有稳定 CLI/API。
- 是否支持长期记忆和技能沉淀。
- 能否限制 workspace。
- 能否导出执行 trace。

OpenClaw 关注点：

- 权限面更大，需要更强沙箱。
- 是否适合部署在当前 VPS。
- 是否需要独立容器或独立机器。
- 能否禁用高风险集成。

验收：

- 输出一份接入评估文档。
- 明确是否接入、以什么权限接入、需要哪些沙箱配置。

## 8. 后端设计要求

### 8.1 Runtime Registry

建议新增：

```text
runtimes/
  __init__.py
  registry.py
  handmade.py
  opencode.py
```

Runtime 统一接口：

```python
class AgentRuntime:
    id: str
    label: str
    description: str
    capabilities: dict

    def available(self) -> bool:
        ...

    def stream_chat(self, request, event_sink):
        ...
```

### 8.2 统一请求结构

```python
{
    "runtime": "handmade",
    "model": "deepseek-v4-flash",
    "messages": [...],
    "trusted_tools": [...],
    "session_id": "..."
}
```

### 8.3 统一响应事件

所有 Runtime 必须尽量翻译为当前事件协议。

最低必需：

```text
message_start
text_delta
message_done
error
```

支持工具的 Runtime 增加：

```text
tool_start
tool_result
tool_error
tool_awaiting_approval
```

### 8.4 失败兜底

如果 runtime 不可用，返回：

```json
{
  "error": "Agent Runtime 不可用：opencode 未安装或未配置"
}
```

SSE 中返回：

```text
event: error
data: {"message":"Agent Runtime 不可用：opencode 未安装或未配置"}
```

## 9. 安全要求

### 9.1 Runtime 权限边界

每个 Runtime 必须声明：

```text
是否可读文件
是否可写文件
是否可执行 shell
是否可访问网络
是否有长期记忆
是否可访问浏览器/外部应用
workspace 范围
```

### 9.2 Workspace 限制

默认限制在项目目录：

```text
/Users/airr/Developer/playground/agent_build_codex
```

或部署容器中的：

```text
/app
```

不允许默认访问：

```text
~/.ssh
.env.production
系统根目录
VPS home 全目录
```

### 9.3 审批策略

保留现有审批机制：

- 文件写入需要确认。
- 文件编辑需要确认。
- 变更类 shell 需要确认。
- 危险 shell 命令后端拦截。

外部 Runtime 如果不能逐步暴露工具步骤，第一阶段应标记为：

```text
实验性
不建议执行写操作
```

## 10. 前端设计要求

### 10.1 Runtime 选择器

初版可以放在输入框附近，和模型选择器并列：

```text
[Agent: Handmade] [Model: DeepSeek V4 Flash] [输入框]
```

后续如果选项增多，可以放入设置面板。

### 10.2 Runtime 不可用状态

不可用 Runtime 置灰，展示原因：

```text
OpenCode 未安装
Hermes 未配置
OpenClaw 未启用沙箱
```

### 10.3 会话级保存

创建会话时使用当前选中的 runtime。

切换会话时恢复该会话 runtime。

### 10.4 消息元信息

assistant 消息保存：

```ts
{
  model?: string;
  runtime?: string;
  steps?: ToolStep[];
}
```

展示：

```text
使用 Agent：Handmade Agent
使用模型：MiMo V2.5
```

## 11. 指标与验收

### 11.1 产品指标

- 用户能理解“Agent”和“Model”的区别。
- 用户能稳定切换回 `handmade`。
- Runtime 切换不会破坏现有会话和模型选择。
- 外部 Runtime 不可用时，错误提示明确。

### 11.2 技术验收

Phase 1：

- `GET /api/runtimes` 可用。
- `/api/chat/stream` 支持 `runtime` 字段。
- `handmade` runtime 行为与现有逻辑一致。
- 前端会话保存 `runtimeId`。
- 后端单测覆盖 runtime registry 和 unknown runtime。
- 前端 build 通过。

Phase 2：

- OpenCode adapter 能完成一次只读任务。
- OpenCode adapter 的 stdout/stderr 不会直接污染 SSE 协议。
- OpenCode 不可访问工作区外路径。
- 失败时前端收到 `error` 事件，而不是页面卡死。

## 12. 主要风险

| 风险 | 说明 | 缓解 |
| --- | --- | --- |
| Runtime 协议差异大 | 第三方 Agent 不一定有结构化工具事件。 | 第一阶段只统一文本流和完成事件，工具事件逐步增强。 |
| 权限面扩大 | OpenClaw 等 Runtime 可能具备本机自动化能力。 | 独立容器、workspace 限制、默认关闭高危能力。 |
| 前端复杂度上升 | 同时有模型和 Runtime 两种选择。 | 文案明确区分：Agent 是执行架构，Model 是大模型。 |
| 会话兼容问题 | 旧会话没有 `runtimeId`。 | 迁移时默认补 `handmade`。 |
| 部署复杂度上升 | 外部 Runtime 可能需要额外二进制或服务。 | Runtime `available=false` 并给出配置原因。 |

## 13. 建议优先级

第一优先级：

```text
Runtime 抽象 + Handmade 迁移
```

第二优先级：

```text
OpenCode adapter
```

第三优先级：

```text
Hermes / OpenClaw 接入评估
```

## 14. 开放问题

- OpenCode 采用 CLI 子进程还是独立服务更合适？
- 外部 Runtime 的工具审批能否映射到当前审批卡片？
- Runtime 是否允许每个会话独立配置 workspace？
- 长期记忆应该由 Runtime 自己管理，还是统一进项目的会话/摘要系统？
- OpenClaw 是否必须运行在独立沙箱容器中？

## 15. 推荐结论

建议做这个功能，但分两步：

1. 先建立 Runtime Adapter 协议，把当前手写 Agent 包成 `handmade` runtime。
2. 再接入 OpenCode 作为第一个外部 runtime。

这样前端可以保持稳定，底层 Agent 架构可以逐步替换和对比。项目不会被某一个第三方 Agent 框架绑定，也不会因为一次性接入过多 Runtime 而失去安全边界。
