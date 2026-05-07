# Turn 回滚重试技术方案

## 1. 背景

当前项目已经具备 Multi-runtime Agent Workbench 架构，支持：

- `handmade` runtime
- `opencode` runtime
- `claude-code` runtime
- 统一 SSE 事件协议
- 统一 session / artifact / tool step 模型

在这种架构下，一条 assistant 消息背后可能不仅包含文本回答，还包含真实工作区副作用，例如：

- 文件创建
- 文件修改
- 文件删除
- 命令执行带来的本地状态变化
- 产物生成

因此，Coding Agent 场景中的“重试”不能简单等同于普通聊天产品中的 regenerate。

如果不恢复工作区状态就直接重新执行，可能导致：

- 重复 patch
- 重复插入代码
- 覆盖已存在结果
- 在错误状态上继续叠加副作用

本方案聚焦实现一种更严格的技术语义：

> 回滚本轮并重试

即：恢复当前 Turn 的工作区文件状态到执行前，再重新运行该 Turn 对应的用户请求。

---

## 2. 设计目标

### 2.1 核心目标

- 为单个 Turn 提供可验证的文件级回滚能力
- 将“回滚本轮并重试”统一收敛到 Workbench 外层，而不是依赖 runtime 原生 rewind
- 对 `handmade / opencode / claude-code` 提供统一语义
- 保持前端入口简单：继续使用当前重试 icon
- 只在“可安全回滚”时允许执行

### 2.2 技术目标

- 引入 `TurnRecord` 与 `TurnFileChange` 数据模型
- 记录本轮工作区文件变更前后状态
- 支持基于 after-state 的冲突检测
- 支持 `create / update / delete / rename` 四类文件操作回滚
- 回滚成功后自动发起新一轮运行
- 旧 Turn 保留状态标记，保证会话可追溯

---

## 3. 非目标

本期不处理：

- 外部系统副作用回滚
- 数据库写入回滚
- HTTP 写请求回滚
- 后台进程状态回滚
- 依赖环境回滚（如 `npm install`）
- 多轮事务式回滚
- 分叉重做
- Git commit / branch 级回滚

本期只承诺：

> 工作区文本文件级回滚

---

## 4. 核心结论

### 4.1 重试语义不由 runtime 原生 session 提供

`claude-code` 与 `opencode` 的 native session / resume 语义更偏向：

- 继续当前会话
- 在当前工作区状态上接着做

但本需求需要的是：

- 回到本轮执行前的工作区状态
- 再重新执行同一轮用户请求

因此，本方案中：

- runtime 只负责执行
- workbench 层负责记录 Turn 文件变更
- workbench 层负责回滚
- 回滚后由 workbench 再触发新一轮运行

### 4.2 重试是 Turn 级能力，不是 Message 级文本能力

要实现“回滚本轮并重试”，系统必须把一次用户请求执行抽象为 Turn，而不是只看 assistant message 文本。

Turn 应覆盖：

- user message
- assistant message
- tool steps
- touched files
- artifacts
- runtime session ref
- status

---

## 5. 总体架构

```text
Frontend Retry Icon
  -> Retry Confirm Popover
    -> Next.js API Route
      -> Python Turn Rollback Service
        -> Turn Store
        -> Workspace Rollback Engine
        -> Runtime Dispatcher
          -> handmade / opencode / claude-code
```

职责划分：

### 前端
- 继续使用当前重试 icon
- 展示轻量确认提示
- 调用回滚重试接口
- 展示旧 Turn 状态与新 Turn 结果

### Next.js API Route
- 转发回滚重试请求到 Python 后端
- 统一前端请求结构

### Python Backend
- 查询 turn 元数据
- 检查是否可安全回滚
- 执行 workspace rollback
- 标记旧 Turn 状态
- 发起新一轮 runtime.run
- 返回新的 Turn / message 结果

### Runtime Adapter
- 继续负责实际执行
- 不承担回滚语义

---

## 6. 核心对象设计

## 6.1 TurnRecord

建议新增 Turn 级记录对象：

```python
class TurnRecord(TypedDict):
    turn_id: str
    session_id: str
    runtime_id: str
    model_id: str
    user_message_id: str
    assistant_message_id: str
    user_message_content: str
    trusted_tools: list[str]
    status: str  # running / done / error / rolled_back / rollback_failed
    side_effect_level: str  # none / workspace_reversible / workspace_conflicted / external_irreversible
    file_changes: list["TurnFileChange"]
    artifact_ids: list[str]
    runtime_session_ref: dict | None
    created_at: float
    completed_at: float | None
    rolled_back_at: float | None
    retry_of_turn_id: str | None
```

关键点：

- `user_message_content` 必须保存原始发送内容
- `retry_of_turn_id` 用于关联新旧 Turn
- `file_changes` 是回滚能力核心

---

## 6.2 TurnFileChange

```python
class TurnFileChange(TypedDict):
    path: str
    operation: str  # create / update / delete / rename
    before_content: str | None
    after_content: str | None
    before_hash: str | None
    after_hash: str | None
    old_path: str | None
    new_path: str | None
    encoding: str  # utf-8
```

### 设计要求

必须满足：

- 能恢复到 `before_content`
- 能判断当前工作区是否仍停留在 `after_content`
- 能支持 rename 回滚

### 为什么同时保存 content 和 hash

- `hash` 用于快速冲突检测
- `content` 用于真正恢复文件

对于大文件后续可优化为 patch 存储，但第一期直接存全文更可靠。

---

## 6.3 Side Effect Level

```text
none
workspace_reversible
workspace_conflicted
external_irreversible
```

含义：

- `none`：无副作用，仅文本
- `workspace_reversible`：仅工作区文件改动，可回滚
- `workspace_conflicted`：检测到文件已变化，不可安全回滚
- `external_irreversible`：存在本期不承诺自动回滚的副作用

### 第一版建议判定规则

- 若有文件写入/编辑/删除/重命名 → `workspace_reversible`
- 若运行后检测冲突 → 动态升级为 `workspace_conflicted`
- 若发生外部写类行为 → `external_irreversible`

---

## 7. Turn 记录时机

## 7.1 Turn 创建时机

在收到用户消息并准备发起 runtime.run 之前创建 TurnRecord：

```text
user submit
  -> create turn_id
  -> persist initial TurnRecord(status=running)
  -> call runtime.run(...)
```

## 7.2 文件变更记录时机

必须在所有写类工具执行时记录。

推荐接入点：

- `handmade`：在工具 registry 的写类工具中统一封装
- `opencode / claude-code`：从 runtime adapter 的 artifact / touched paths / diff 归并后生成记录

### Handmade

对于：

- `file_write`
- `file_edit`
- 未来的 rename/delete 工具

在执行前后记录：

1. 读取 `before_content`
2. 执行写操作
3. 读取 `after_content`
4. append 到当前 Turn 的 `file_changes`

### Claude Code / OpenCode

由于文件写入可能不是通过本项目 registry 直接发生，因此需要在 adapter 层做归并：

- 从 runtime 原生事件收集 touched files
- 在 turn 完成后对 touched files 做一次 `before/after` 对照补录

但这要求在 Turn 开始前先采集 baseline。

---

## 8. Baseline 采集策略

对于非 handmade runtime，需要在 Turn 开始前建立工作区快照基线。

### 8.1 第一版推荐策略

只对“被本轮触达的文件”做 lazy baseline。

过程：

1. Turn 开始时建立空 baseline map
2. 当 runtime 首次触达某个文件时：
   - 如果 baseline 尚未记录
   - 立即读取当前文件内容作为 `before_content`
3. Turn 结束时再读取最终文件内容作为 `after_content`

### 8.2 优点

- 不需要全量扫描 workspace
- 对大仓库更轻量

### 8.3 风险

- 必须可靠识别 touched files
- 如果 runtime 写了文件但没上报 touched path，会漏记

### 8.4 第一阶段建议

Phase 1 优先只支持 `handmade` 的严格回滚；
对 `claude-code / opencode` 先保留接口和模型，后续增强。

---

## 9. 冲突检测设计

## 9.1 核心原则

只有当当前工作区仍等于该 Turn 完成时的 after 状态，才允许自动回滚。

否则说明：

- 用户手动改过文件
- 后续 Turn 又改过文件
- 当前文件已不再是该 Turn 的结果

此时不能自动覆盖。

## 9.2 检测规则

对每个 `TurnFileChange` 执行：

### create
- 当前文件存在，且 hash == `after_hash` → 可安全删除
- 否则 → 冲突

### update
- 当前文件存在，且 hash == `after_hash` → 可恢复 `before_content`
- 否则 → 冲突

### delete
- 当前文件不存在 → 可恢复 `before_content`
- 当前文件已重新出现 → 冲突

### rename
- 需检查 old_path / new_path 当前状态与记录是否一致
- 任一不一致 → 冲突

## 9.3 冲突结果

一旦任一文件冲突：

- 整个 Turn 回滚失败
- 不执行部分回滚
- `TurnRecord.status = rollback_failed`
- `side_effect_level = workspace_conflicted`

采用整轮失败而非部分回滚的原因：

- 保证语义清晰
- 避免出现部分文件回退、部分未回退的中间态

---

## 10. 回滚引擎设计

## 10.1 Rollback Service 接口

建议新增服务层：

```python
class TurnRollbackService:
    def can_rollback(self, turn_id: str) -> tuple[bool, str | None]:
        ...

    def rollback_turn(self, turn_id: str) -> None:
        ...

    def rollback_and_retry(self, turn_id: str) -> dict:
        ...
```

## 10.2 回滚执行顺序

建议按逆序执行文件回滚：

```text
for change in reversed(file_changes):
    rollback(change)
```

原因：

- 更接近实际操作栈
- rename / create / delete 混合场景更安全

## 10.3 不同操作的回滚动作

### update
- 用 `before_content` 覆盖当前文件

### create
- 删除该文件

### delete
- 重新写回 `before_content`

### rename
- 将 `new_path` 恢复为 `old_path`
- 恢复原内容

---

## 11. Retry 执行设计

## 11.1 回滚成功后如何重试

回滚成功后，新建一个 TurnRecord，然后重新调用原 runtime：

```text
old turn rolled_back
  -> create new turn(retry_of_turn_id=old_turn_id)
  -> runtime.run(request_from_old_turn)
```

## 11.2 新 Turn 的输入来源

直接复用旧 Turn 的：

- `session_id`
- `runtime_id`
- `model_id`
- `trusted_tools`
- `user_message_content`

但是：

- 工作区已回滚到旧 Turn 开始前状态
- 新 Turn 使用新的 `turn_id`
- 新 Turn 产生新的 message / steps / artifacts

## 11.3 会话消息处理建议

会话层不删除旧 Turn 消息。

推荐策略：

- 旧 assistant message 保留，标记 `rolled_back`
- 新 assistant message 正常插入为后续结果
- UI 根据 `retry_of_turn_id` 可选择弱关联展示

---

## 12. 前后端接口建议

## 12.1 前端调用接口

建议新增：

```text
POST /api/turns/:turnId/retry
```

请求体可为空，或预留：

```json
{
  "mode": "rollback_retry"
}
```

## 12.2 Python Backend 接口

建议在后端新增：

```text
POST /api/turns/<turn_id>/retry
```

返回：

```json
{
  "ok": true,
  "rolled_back_turn_id": "turn_old",
  "new_turn_id": "turn_new",
  "assistant_message_id": "assistant_new",
  "status": "started"
}
```

如果失败：

```json
{
  "ok": false,
  "error": "检测到文件冲突，无法安全回滚",
  "code": "ROLLBACK_CONFLICT"
}
```

## 12.3 前端轻量提示配合

点击重试 icon 后：

1. 展示轻量 Popover
2. 确认后调用 `/api/turns/:turnId/retry`
3. 成功后把旧消息标记为 `已回滚`
4. 接收新一轮 SSE 或轮询状态

---

## 13. Turn Store 持久化建议

第一版建议不要只存前端 localStorage，后端也需要有 Turn Store。

### 推荐位置

可先使用项目内本地 JSON 文件：

```text
.workbuddy/turn-store.json
```

或拆分：

```text
.workbuddy/turns/<session_id>/<turn_id>.json
```

### 推荐原因

- 回滚发生在后端
- 后端必须知道旧 Turn 的 file_changes
- 前端 localStorage 不足以承担可信回滚数据源

### 后续演进

后续可迁移为 SQLite。

---

## 14. 与现有代码结构的结合建议

## 14.1 前端

当前 `frontend/src/components/agent-chat.tsx` 已有：

- message 操作区
- retry icon
- tool steps / artifacts / runtime 元信息

后续只需增加：

- turn_id 存储到 assistant message
- 重试 icon 调用新的 turn retry 接口
- 旧 Turn 状态展示

## 14.2 后端

当前 `server.py` 已有：

- `/api/chat`
- `/api/chat/stream`
- runtime registry
- runtime session ref

建议新增：

```text
turns/
  __init__.py
  store.py
  recorder.py
  rollback.py
```

职责：

- `store.py`：持久化 TurnRecord
- `recorder.py`：记录 file_changes
- `rollback.py`：执行回滚与重试

---

## 15. 风险与约束

## 15.1 最大风险：文件变更漏记

如果某些写操作未进入 `file_changes`，回滚将不可信。

因此第一阶段应优先保证：

- 所有 handmade 写类工具必须统一接入 recorder
- 先不要承诺 `claude-code / opencode` 完整回滚

## 15.2 用户手动修改冲突

这是必须阻断的场景。

宁可提示失败，也不能静默覆盖用户后续修改。

## 15.3 非文件副作用误解

用户可能以为“回滚并重试”会撤销所有行为。

因此前端文案与 PRD 都必须明确：

> 当前只保证工作区文件级回滚

---

## 16. 分阶段建议

## Phase 1

范围：

- 仅支持 `handmade`
- 支持 `create / update / delete`
- 增加 TurnStore / TurnFileChange / RollbackService
- 接入当前重试 icon
- 轻量 Popover 说明

验收：

- 能安全回滚单轮文件改动
- 回滚成功后自动重新执行
- 冲突时不覆盖用户修改

## Phase 2

范围：

- 支持 rename
- 支持 turn 改动摘要展示
- 为 `claude-code / opencode` 补齐 touched file baseline 机制

---

## 17. 最终建议

技术上应采用：

1. **Turn 级记录**，而不是 message 级文本重试
2. **Workbench 统一回滚**，而不是依赖 runtime native rewind
3. **文件级可验证回滚**，而不是模糊的“再跑一次”
4. **整轮冲突即失败**，避免部分回滚中间态
5. **Phase 1 先做 handmade 闭环**，再扩展到 Claude Code / OpenCode

这条路线最稳，也最符合当前项目架构。