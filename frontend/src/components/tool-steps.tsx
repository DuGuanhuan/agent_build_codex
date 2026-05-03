"use client";

import { CheckCircle2, ChevronDown, Clock3, Wrench, XCircle, AlertTriangle } from "lucide-react";
import { useState } from "react";

import type { ToolStep } from "@/lib/types";
import { cn } from "@/lib/utils";

function formatJson(value: unknown) {
  if (value === undefined || value === null) {
    return "";
  }

  return JSON.stringify(value, null, 2);
}

function statusLabel(step: ToolStep) {
  if (step.status === "error" || step.type === "tool_error") {
    return "失败";
  }
  if (step.status === "running") {
    return "执行中";
  }
  if (step.status === "awaiting_approval") {
    return "待审批";
  }
  return "成功";
}

function statusClass(step: ToolStep) {
  if (step.status === "error" || step.type === "tool_error") {
    return "border-rose-200 bg-rose-50 text-rose-700";
  }
  if (step.status === "running") {
    return "border-sky-200 bg-sky-50 text-sky-700";
  }
  if (step.status === "awaiting_approval") {
    return "border-amber-400 bg-amber-100 text-amber-800 shadow-sm shadow-amber-200/50";
  }
  return "border-emerald-200 bg-emerald-50 text-emerald-700";
}

export function ToolSteps({ steps, onAction, disabled }: { steps: ToolStep[]; onAction?: (action: string) => void; disabled?: boolean }) {
  const [open, setOpen] = useState(false);

  if (!steps.length) {
    return null;
  }

  return (
    <div className="mt-3">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="inline-flex items-center gap-1.5 rounded-full border border-stone-200 bg-stone-100 px-3 py-1.5 text-xs font-semibold text-stone-600 transition hover:bg-stone-200"
      >
        <Wrench className="h-3.5 w-3.5" />
        {steps.length} 个工具调用
        <ChevronDown className={cn("h-3.5 w-3.5 transition", open && "rotate-180")} />
      </button>

      {open ? (
        <div className="mt-2 grid gap-2 rounded-xl border border-stone-200 bg-stone-100/70 p-3 text-xs leading-relaxed text-stone-600">
          {steps.map((step, index) => (
            <div
              key={step.id || `${step.tool}-${index}`}
              className="rounded-lg border border-stone-200 bg-white p-3"
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className={cn("inline-flex items-center gap-1 rounded-full border px-2 py-0.5 font-semibold", statusClass(step))}>
                  {step.status === "error" || step.type === "tool_error" ? (
                    <XCircle className="h-3.5 w-3.5" />
                  ) : step.status === "awaiting_approval" ? (
                    <AlertTriangle className="h-3.5 w-3.5" />
                  ) : (
                    <CheckCircle2 className="h-3.5 w-3.5" />
                  )}
                  {statusLabel(step)}
                </span>
                <span className="font-mono font-bold text-stone-900">{step.tool}</span>
                {step.permission ? (
                  <span className="rounded-full bg-stone-100 px-2 py-0.5 font-mono text-[11px] text-stone-500">
                    {step.permission}
                  </span>
                ) : null}
                {typeof step.duration_ms === "number" ? (
                  <span className="inline-flex items-center gap-1 text-stone-400">
                    <Clock3 className="h-3.5 w-3.5" />
                    {step.duration_ms}ms
                  </span>
                ) : null}
              </div>

              <div className="mt-3 grid gap-2 md:grid-cols-2">
                <div>
                  <div className="mb-1 font-semibold text-stone-500">参数</div>
                  <pre className="max-h-48 overflow-auto rounded-md bg-stone-950 p-2 font-mono text-[11px] leading-5 text-stone-100">
                    {formatJson(step.args) || "{}"}
                  </pre>
                </div>
                <div>
                  <div className="mb-1 font-semibold text-stone-500">
                    {step.error ? "错误" : step.status === "awaiting_approval" ? "等待您的审批" : "结果"}
                  </div>
                  {step.status === "awaiting_approval" ? (
                    <div className="flex h-full min-h-24 flex-col items-center justify-center gap-3 rounded-md border border-amber-200 bg-amber-50/50 p-4">
                      <span className="text-center font-medium text-amber-800">
                        Agent 请求执行一个高危操作。请仔细确认参数。
                      </span>
                      <div className="flex gap-2">
                        <button
                          type="button"
                          disabled={disabled}
                          onClick={() => {
                            const reason = window.prompt("请输入拒绝理由（可选）：") || "无";
                            onAction?.(JSON.stringify({ __system_action: "reject_tool", reason }));
                          }}
                          className="rounded-md border border-rose-200 bg-white px-3 py-1.5 font-semibold text-rose-600 shadow-sm hover:bg-rose-50 disabled:opacity-50"
                        >
                          拒绝执行
                        </button>
                        <button
                          type="button"
                          disabled={disabled}
                          onClick={() => onAction?.(JSON.stringify({ __system_action: "approve_tool" }))}
                          className="rounded-md border border-emerald-600 bg-emerald-600 px-3 py-1.5 font-semibold text-white shadow-sm hover:bg-emerald-700 disabled:opacity-50"
                        >
                          允许执行
                        </button>
                      </div>
                    </div>
                  ) : (
                    <pre
                      className={cn(
                        "max-h-48 overflow-auto rounded-md p-2 font-mono text-[11px] leading-5",
                        step.error ? "bg-rose-950 text-rose-50" : "bg-stone-950 text-stone-100",
                      )}
                    >
                      {step.error || formatJson(step.result) || "{}"}
                    </pre>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
