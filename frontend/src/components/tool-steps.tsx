"use client";

import {
  AlertCircle,
  Bot,
  Check,
  ChevronDown,
  ChevronRight,
  FileText,
  Globe,
  MessageCircleQuestion,
  Loader2,
  Search,
  Terminal,
  Wrench,
} from "lucide-react";
import { useState } from "react";

import type { ToolStep } from "@/lib/types";
import { cn } from "@/lib/utils";

/* ═══════════════════════════════════════════════════════════════════
   Helpers
   ═══════════════════════════════════════════════════════════════════ */

function ToolIcon({ name, className }: { name: string; className?: string }) {
  const c = cn("h-3.5 w-3.5 flex-shrink-0", className);
  const normalized = name.toLowerCase();
  switch (normalized) {
    case "shell_exec":
    case "bash":
      return <Terminal className={c} />;
    case "file_read":
    case "file_write":
    case "file_edit":
    case "read":
    case "write":
    case "edit":
      return <FileText className={c} />;
    case "web_fetch":
    case "webfetch":
      return <Globe className={c} />;
    case "repo_search":
    case "grep":
    case "glob":
    case "websearch":
      return <Search className={c} />;
    case "askuserquestion":
      return <MessageCircleQuestion className={c} />;
    case "task":
    case "taskoutput":
      return <Bot className={c} />;
    default:
      return <Wrench className={c} />;
  }
}

function summarize(step: ToolStep): string {
  const a = step.args || {};
  const tool = step.tool.toLowerCase();
  switch (tool) {
    case "shell_exec":
    case "bash":
      return (a.description as string) || `执行命令：${(a.command as string) || ""}`;
    case "file_read":
    case "read":
      return `准备读取 ${a.path || "文件"}`;
    case "file_write":
    case "write":
      return `准备创建并写入 ${a.path || "文件"}`;
    case "file_edit":
    case "edit":
      return `准备编辑 ${a.path || "文件"}`;
    case "repo_search":
    case "grep":
      return `正在搜索项目：${a.query || ""}`;
    case "glob":
      return `正在匹配文件：${a.pattern || ""}`;
    case "web_fetch":
    case "webfetch":
      return `准备访问网页：${a.url || ""}`;
    case "websearch":
      return `正在联网搜索：${a.query || ""}`;
    case "askuserquestion": {
      const questions = Array.isArray(a.questions) ? a.questions : [];
      const firstQuestion = questions[0] && typeof questions[0] === "object"
        ? (questions[0] as Record<string, unknown>).question
        : null;
      return typeof firstQuestion === "string" ? `等待用户回答：${firstQuestion}` : "等待用户补充信息";
    }
    case "task":
      return `启动子 Agent：${a.description || a.subagent_type || "执行专项任务"}`;
    case "taskoutput":
      return "读取子 Agent 输出";
    default:
      return `调用工具：${step.tool}`;
  }
}

function resultSummary(step: ToolStep): string | null {
  if (step.error) return null;
  const r = step.result as Record<string, unknown> | undefined;
  if (!r || typeof r !== "object") return null;

  const tool = step.tool.toLowerCase();
  if (tool === "shell_exec" || tool === "bash") {
    const code = (r.exit_code ?? r.exit) as number | undefined;
    if (code === 0) return "命令执行成功";
    return typeof code === "number" ? `执行结束 (退出码 ${code})` : "命令执行完成";
  }
  if (tool === "file_read" || tool === "read") {
    return `已读取文件，共 ${r.total_lines || 0} 行`;
  }
  if (tool === "file_write" || tool === "write") return "文件已保存";
  if (tool === "file_edit" || tool === "edit") return "文件已更新";
  if (tool === "repo_search" || tool === "grep" || tool === "glob" || tool === "websearch") {
    return typeof r.count === "number" ? `找到 ${r.count} 条结果` : "搜索完成";
  }
  if (tool === "web_fetch" || tool === "webfetch") return "内容读取完成";
  if (tool === "askuserquestion") return "用户问题处理完成";
  if (tool === "task") return "子 Agent 执行完成";
  if (tool === "taskoutput") return "子 Agent 输出已读取";
  return "执行完成";
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

type AskOption = {
  label?: string;
  description?: string;
};

type AskQuestion = {
  header?: string;
  question?: string;
  options?: AskOption[];
};

function askQuestion(step: ToolStep): AskQuestion | null {
  if (step.tool.toLowerCase() !== "askuserquestion") {
    return null;
  }
  const questions = step.args && Array.isArray(step.args.questions) ? step.args.questions : [];
  const first = questions[0];
  if (!first || typeof first !== "object") {
    return null;
  }
  return first as AskQuestion;
}

function answerAction(step: ToolStep, question: AskQuestion, option: AskOption) {
  return JSON.stringify({
    __system_action: "answer_user_question",
    tool: step.tool,
    tool_call_id: step.id,
    header: question.header || "",
    question: question.question || "",
    label: option.label || option.description || "已选择",
    description: option.description || "",
    answer: option.label || option.description || "已选择",
  });
}

/* ═══════════════════════════════════════════════════════════════════
   Details Block
   ═══════════════════════════════════════════════════════════════════ */

function DetailBlock({ label, content, isCode = true }: { label: string; content: string; isCode?: boolean }) {
  if (!content.trim()) return null;
  return (
    <div className="space-y-1.5">
      <div className="text-[10px] font-bold text-muted-soft uppercase tracking-[0.1em]">{label}</div>
      <pre className={cn(
        "max-h-64 overflow-auto rounded-xl border border-hairline bg-surface-soft/30 p-3 text-[11px] leading-relaxed",
        isCode ? "font-mono text-body" : "text-body"
      )}>
        {content}
      </pre>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════
   Tool Step Item
   ═══════════════════════════════════════════════════════════════════ */

function StepItem({
  step,
  onAction,
  disabled,
}: {
  step: ToolStep;
  onAction?: (action: string) => void;
  disabled?: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const [trustSession, setTrustSession] = useState(false);

  const isApproval = step.status === "awaiting_approval";
  const question = askQuestion(step);
  const isAskQuestionApproval = isApproval && Boolean(question);
  const isRunning = step.status === "running";
  const isError = step.status === "error" || step.type === "tool_error";
  const isDone = !isApproval && !isRunning;

  const summary = isDone ? (resultSummary(step) || summarize(step)) : summarize(step);
  const coreArg = step.args ? (step.args.command || step.args.path || step.args.url || step.args.query) : null;
  const coreArgText = coreArg == null ? "" : typeof coreArg === "string" ? coreArg : JSON.stringify(coreArg);
  const result = step.result && typeof step.result === "object" ? (step.result as Record<string, unknown>) : null;
  const stdout =
    typeof result?.stdout === "string"
      ? result.stdout
      : typeof result?.output === "string"
        ? result.output
        : "";
  const stderr = typeof result?.stderr === "string" ? result.stderr : "";

  return (
    <div className={cn(
      "mb-2.5 overflow-hidden rounded-2xl border border-hairline bg-white/40 transition-all",
      isApproval ? "border-amber-200/60 bg-amber-50/[0.03] ring-1 ring-amber-500/10 shadow-sm" : "hover:bg-white/80 hover:shadow-sm"
    )}>
      {/* 头部行：点击切换展开/收起 */}
      <div 
        className="flex cursor-pointer items-center justify-between px-3 py-2.5"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex min-w-0 items-center gap-2.5">
          <div className={cn(
            "grid h-6 w-6 shrink-0 place-items-center rounded-lg shadow-sm ring-1 ring-black/[0.03]",
            isApproval ? "bg-amber-100 text-amber-600" : 
            isRunning ? "bg-blue-50 text-blue-500" : 
            isError ? "bg-rose-50 text-rose-500" : "bg-surface-soft text-muted-soft"
          )}>
            {isRunning ? <Loader2 className="h-3 w-3 animate-spin" /> : <ToolIcon name={step.tool} />}
          </div>
          
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="text-[11px] font-bold text-ink uppercase tracking-wider">{step.tool}</span>
              <span className="text-hairline">·</span>
              <span className={cn(
                "text-[10px] font-bold uppercase tracking-widest",
                isApproval ? "text-amber-600" : 
                isRunning ? "text-blue-500" : 
                isError ? "text-rose-500" : "text-emerald-600"
              )}>
                {isApproval ? "待确认" : isRunning ? "执行中" : isError ? "失败" : "已完成"}
              </span>
              {isDone && typeof step.duration_ms === "number" && (
                <span className="text-[10px] font-medium text-muted-soft">{formatDuration(step.duration_ms)}</span>
              )}
            </div>
            <p className={cn(
              "truncate text-[13px] font-medium leading-relaxed",
              isApproval ? "text-ink" : "text-body"
            )}>
              {summary}
            </p>
          </div>
        </div>
        
        <div className="flex items-center gap-2 text-stone-400">
          <ChevronRight className={cn("h-4 w-4 transition-transform", expanded && "rotate-90")} />
        </div>
      </div>

      {/* 审批控制台 */}
      {isAskQuestionApproval && question && (
        <div className="border-t border-hairline bg-amber-50/[0.01] p-3.5">
          <div className="mb-3 space-y-1 rounded-xl border border-amber-200/40 bg-white/70 p-3.5 shadow-sm">
            {question.header && (
              <div className="text-[10px] font-bold uppercase tracking-[0.14em] text-amber-600">
                {question.header}
              </div>
            )}
            <p className="text-[13px] font-semibold leading-relaxed text-ink">
              {question.question || "Claude Code 需要你补充一个选择"}
            </p>
          </div>

          <div className="grid gap-2">
            {(question.options && question.options.length ? question.options : [{ label: "继续", description: "" }]).map((option, index) => (
              <button
                key={`${option.label || "option"}-${index}`}
                type="button"
                disabled={disabled}
                onClick={(event) => {
                  event.stopPropagation();
                  onAction?.(answerAction(step, question, option));
                }}
                className="group cursor-pointer rounded-xl border border-hairline bg-white px-3.5 py-3 text-left shadow-sm transition hover:border-primary-coral/40 hover:bg-primary-coral/5 active:scale-[0.99] disabled:cursor-not-allowed disabled:opacity-40"
              >
                <div className="text-[13px] font-bold leading-snug text-ink group-hover:text-primary-coral">
                  {option.label || option.description || "继续"}
                </div>
                {option.description && (
                  <div className="mt-1 text-[12px] leading-relaxed text-muted-soft">
                    {option.description}
                  </div>
                )}
              </button>
            ))}
          </div>
        </div>
      )}

      {isApproval && !isAskQuestionApproval && (
        <div className="border-t border-hairline bg-amber-50/[0.01] p-3.5">
          <div className="mb-4 flex items-start gap-3 rounded-xl border border-amber-200/40 bg-white/60 p-3.5 shadow-sm">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
            <div className="min-w-0 flex-1 space-y-2.5">
              <p className="text-[13px] leading-relaxed text-body">
                该操作需要你的确认。它将执行命令或访问本地文件，请确保来源可信。
              </p>
              {coreArgText && (
                <div className="rounded-lg bg-surface-soft px-2.5 py-2 font-mono text-[11px] text-body ring-1 ring-black/[0.02]">
                  {coreArgText}
                </div>
              )}
            </div>
          </div>
          
          <div className="flex items-center justify-between">
            <label className="flex cursor-pointer items-center gap-2 text-[11px] font-bold text-muted-soft hover:text-ink transition-colors">
              <input
                type="checkbox"
                checked={trustSession}
                onChange={(e) => setTrustSession(e.target.checked)}
                className="h-3.5 w-3.5 rounded-md border-hairline text-primary focus:ring-0"
              />
              <span className="uppercase tracking-widest">始终信任此工具</span>
            </label>
            <div className="flex items-center gap-2">
              <button
                type="button"
                disabled={disabled}
                onClick={(e) => { e.stopPropagation(); onAction?.(JSON.stringify({ __system_action: "reject_tool", reason: "用户拒绝" })); }}
                className="cursor-pointer rounded-xl px-4 py-2 text-[11px] font-bold text-muted-soft transition hover:bg-surface-soft hover:text-ink active:scale-95 disabled:cursor-not-allowed disabled:opacity-30"
              >
                拒绝执行
              </button>
              <button
                type="button"
                disabled={disabled}
                onClick={(e) => { e.stopPropagation(); onAction?.(JSON.stringify({ __system_action: "approve_tool", trust_session: trustSession, tool: step.tool })); }}
                className="flex cursor-pointer items-center gap-2 rounded-xl bg-ink px-5 py-2 text-[11px] font-bold text-white shadow-lg shadow-black/10 transition hover:bg-stone-800 active:scale-95 disabled:cursor-not-allowed disabled:opacity-30"
              >
                批准并继续
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 详情区域 */}
      {expanded && (
        <div className="space-y-4 border-t border-stone-200 bg-stone-50/30 p-3 animate-in fade-in slide-in-from-top-1 duration-200">
          {/* 参数详情 */}
          {step.args && (
            <DetailBlock label="Tool Arguments" content={JSON.stringify(step.args, null, 2)} />
          )}

          {/* 运行结果详情 */}
          {isDone && (
            <>
              {stdout && (
                <DetailBlock label="Standard Output (stdout)" content={stdout} />
              )}
              {stderr && (
                <div className="space-y-1">
                  <div className="text-[10px] font-bold text-rose-500 uppercase tracking-widest">Error Output (stderr)</div>
                  <pre className="max-h-60 overflow-auto rounded-lg border border-rose-100 bg-rose-50/30 p-2.5 font-mono text-[11px] leading-relaxed text-rose-600">
                    {stderr}
                  </pre>
                </div>
              )}
              {step.error && (
                <DetailBlock label="Error Message" content={step.error} />
              )}
              <DetailBlock label="Raw Result JSON" content={JSON.stringify(step.result, null, 2)} />
            </>
          )}
        </div>
      )}
    </div>
  );
}

export function ToolSteps({
  steps,
  onAction,
  disabled,
}: {
  steps: ToolStep[];
  onAction?: (action: string) => void;
  disabled?: boolean;
}) {
  const hasApproval = steps.some((s) => s.status === "awaiting_approval");
  const hasRunning = steps.some((s) => s.status === "running");
  const allDone = steps.every(
    (s) => s.status !== "awaiting_approval" && s.status !== "running",
  );

  const [manualOpen, setManualOpen] = useState(false);
  const isOpen = manualOpen || hasApproval || hasRunning;

  if (!steps.length) return null;

  /* Summary bar label */
  const label = (() => {
    if (hasApproval) return "工具调用 · 需要确认";
    if (hasRunning) return "工具调用 · 执行中";
    const errorCount = steps.filter((s) => s.status === "error" || s.type === "tool_error").length;
    if (errorCount > 0) return `${steps.length} 个工具调用 · ${errorCount} 个失败`;
    return `使用了 ${steps.length} 个工具`;
  })();

  return (
    <div className="mt-2">
      {/* Summary bar */}
      <button
        type="button"
        onClick={() => setManualOpen((v) => !v)}
        className={cn(
          "inline-flex cursor-pointer items-center gap-1.5 text-[12px] transition active:scale-95",
          hasApproval
            ? "font-medium text-amber-600 hover:text-amber-700"
            : "text-stone-400 hover:text-stone-600",
        )}
      >
        {hasApproval ? (
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-amber-400 opacity-75" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-amber-500" />
          </span>
        ) : hasRunning ? (
          <Loader2 className="h-3 w-3 animate-spin" />
        ) : allDone ? (
          <Check className="h-3 w-3" />
        ) : (
          <Wrench className="h-3 w-3" />
        )}
        {label}
        <ChevronDown
          className={cn("h-3 w-3 transition", isOpen && "rotate-180")}
        />
      </button>

      {/* Step cards */}
      {isOpen && (
        <div className="mt-1.5 space-y-1 border-l-2 border-stone-100 pl-3">
          {steps.map((step, index) => (
            <StepItem
              key={step.id || `${step.tool}-${index}`}
              step={step}
              onAction={onAction}
              disabled={disabled}
            />
          ))}
        </div>
      )}
    </div>
  );
}
