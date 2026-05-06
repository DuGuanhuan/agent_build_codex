"use client";

import { Archive, FileDiff, Layers3, ListChecks, RefreshCw, Sparkles } from "lucide-react";
import { useMemo, useState } from "react";

import type { RuntimeArtifact, RuntimeSessionRef } from "@/lib/types";
import { cn } from "@/lib/utils";

type RuntimeWorkbenchPanelProps = {
  artifacts: RuntimeArtifact[];
  sessionRef?: RuntimeSessionRef | null;
  runtimeLabel?: string;
  modelLabel?: string;
  loading?: boolean;
  onRefresh?: () => void;
};

type PanelTab = "diff" | "todo" | "all" | "session";

type RuntimeFileDiff = {
  file: string;
  before?: string;
  after?: string;
  additions?: number;
  deletions?: number;
  status?: "added" | "deleted" | "modified" | string;
  raw?: unknown;
};

type DiffLine = {
  type: "context" | "added" | "deleted";
  text: string;
  oldLine?: number;
  newLine?: number;
};

function artifactText(data: unknown) {
  if (typeof data === "string") return data;
  if (data == null) return "";
  return JSON.stringify(data, null, 2);
}

function artifactCount(artifacts: RuntimeArtifact[], type: string) {
  return artifacts.filter((artifact) => artifact.type === type).length;
}

function normalizeFileDiffs(data: unknown): RuntimeFileDiff[] {
  const value = data && typeof data === "object" && "diffs" in data ? (data as { diffs?: unknown }).diffs : data;
  const items = Array.isArray(value) ? value : value && typeof value === "object" ? [value] : [];

  return items.flatMap((item) => {
    if (!item || typeof item !== "object") return [];
    const record = item as Record<string, unknown>;
    const file =
      typeof record.file === "string"
        ? record.file
        : typeof record.path === "string"
          ? record.path
          : typeof record.name === "string"
            ? record.name
            : "";
    if (!file) return [];
    return [
      {
        file,
        before: typeof record.before === "string" ? record.before : undefined,
        after: typeof record.after === "string" ? record.after : undefined,
        additions: typeof record.additions === "number" ? record.additions : undefined,
        deletions: typeof record.deletions === "number" ? record.deletions : undefined,
        status: typeof record.status === "string" ? record.status : undefined,
        raw: item,
      },
    ];
  });
}

function splitLines(text: string) {
  if (!text) return [];
  return text.replace(/\r\n/g, "\n").split("\n");
}

function buildLineDiff(beforeText = "", afterText = ""): DiffLine[] {
  const before = splitLines(beforeText);
  const after = splitLines(afterText);
  if (!before.length && !after.length) return [];

  if (before.length * after.length > 40_000) {
    return [
      ...before.slice(0, 120).map((text, index) => ({ type: "deleted" as const, text, oldLine: index + 1 })),
      ...after.slice(0, 120).map((text, index) => ({ type: "added" as const, text, newLine: index + 1 })),
    ];
  }

  const lcs = Array.from({ length: before.length + 1 }, () => Array(after.length + 1).fill(0) as number[]);
  for (let i = before.length - 1; i >= 0; i -= 1) {
    for (let j = after.length - 1; j >= 0; j -= 1) {
      lcs[i][j] = before[i] === after[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
    }
  }

  const lines: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < before.length && j < after.length) {
    if (before[i] === after[j]) {
      lines.push({ type: "context", text: before[i], oldLine: i + 1, newLine: j + 1 });
      i += 1;
      j += 1;
    } else if (lcs[i + 1][j] >= lcs[i][j + 1]) {
      lines.push({ type: "deleted", text: before[i], oldLine: i + 1 });
      i += 1;
    } else {
      lines.push({ type: "added", text: after[j], newLine: j + 1 });
      j += 1;
    }
  }
  while (i < before.length) {
    lines.push({ type: "deleted", text: before[i], oldLine: i + 1 });
    i += 1;
  }
  while (j < after.length) {
    lines.push({ type: "added", text: after[j], newLine: j + 1 });
    j += 1;
  }
  return lines;
}

function statusLabel(status?: string) {
  if (status === "added") return "Added";
  if (status === "deleted") return "Deleted";
  if (status === "modified") return "Modified";
  return status || "Changed";
}

function DiffReview({ artifact }: { artifact?: RuntimeArtifact }) {
  const files = useMemo(() => normalizeFileDiffs(artifact?.data), [artifact?.data]);
  const [selectedFile, setSelectedFile] = useState("");

  if (!artifact) {
    return <EmptyPanel text="还没有文件 diff。让 OpenCode 修改文件后，这里会展示变更产物。" />;
  }
  if (!files.length) {
    return <RawArtifact artifact={artifact} />;
  }

  const activeFile = files.find((file) => file.file === selectedFile) || files[0];
  const diffLines = buildLineDiff(activeFile.before, activeFile.after);
  const totalAdditions = files.reduce((sum, file) => sum + (file.additions || 0), 0);
  const totalDeletions = files.reduce((sum, file) => sum + (file.deletions || 0), 0);

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-3 gap-2">
        <div className="rounded-xl border border-hairline bg-white/60 p-3">
          <div className="text-[10px] font-bold uppercase tracking-widest text-muted-soft">Files</div>
          <div className="mt-1 text-lg font-semibold text-ink">{files.length}</div>
        </div>
        <div className="rounded-xl border border-emerald-100 bg-emerald-50/40 p-3">
          <div className="text-[10px] font-bold uppercase tracking-widest text-emerald-700">Added</div>
          <div className="mt-1 text-lg font-semibold text-emerald-700">+{totalAdditions}</div>
        </div>
        <div className="rounded-xl border border-rose-100 bg-rose-50/40 p-3">
          <div className="text-[10px] font-bold uppercase tracking-widest text-rose-700">Deleted</div>
          <div className="mt-1 text-lg font-semibold text-rose-700">-{totalDeletions}</div>
        </div>
      </div>

      <div className="space-y-1.5">
        {files.map((file) => {
          const active = file.file === activeFile.file;
          return (
            <button
              key={file.file}
              type="button"
              onClick={() => setSelectedFile(file.file)}
              className={cn(
                "flex w-full cursor-pointer items-center justify-between gap-3 rounded-xl border px-3 py-2 text-left transition active:scale-[0.99]",
                active ? "border-primary-coral/30 bg-primary-coral/5" : "border-hairline bg-white/50 hover:bg-white",
              )}
            >
              <span className="min-w-0">
                <span className="block truncate font-mono text-[11px] font-semibold text-ink">{file.file}</span>
                <span className="mt-0.5 block text-[10px] font-bold uppercase tracking-widest text-muted-soft">
                  {statusLabel(file.status)}
                </span>
              </span>
              <span className="shrink-0 font-mono text-[11px]">
                <span className="text-emerald-700">+{file.additions || 0}</span>
                <span className="mx-1 text-muted-soft">/</span>
                <span className="text-rose-700">-{file.deletions || 0}</span>
              </span>
            </button>
          );
        })}
      </div>

      <div className="overflow-hidden rounded-xl border border-hairline bg-white/70">
        <div className="border-b border-hairline px-3 py-2 font-mono text-[11px] font-semibold text-ink">
          {activeFile.file}
        </div>
        {diffLines.length ? (
          <pre className="max-h-[52vh] overflow-auto text-[11px] leading-relaxed">
            {diffLines.map((line, index) => (
              <div
                key={`${line.type}-${index}-${line.oldLine || ""}-${line.newLine || ""}`}
                className={cn(
                  "grid grid-cols-[44px_44px_20px_minmax(0,1fr)] gap-2 px-2 font-mono",
                  line.type === "added" && "bg-emerald-50 text-emerald-900",
                  line.type === "deleted" && "bg-rose-50 text-rose-900",
                  line.type === "context" && "text-body",
                )}
              >
                <span className="select-none text-right text-muted-soft">{line.oldLine || ""}</span>
                <span className="select-none text-right text-muted-soft">{line.newLine || ""}</span>
                <span className="select-none text-center">
                  {line.type === "added" ? "+" : line.type === "deleted" ? "-" : " "}
                </span>
                <span className="min-w-0 whitespace-pre-wrap break-words">{line.text || " "}</span>
              </div>
            ))}
          </pre>
        ) : (
          <EmptyPanel text="这个文件没有可显示的文本变更。" />
        )}
      </div>
    </div>
  );
}

function TodoList({ artifact }: { artifact?: RuntimeArtifact }) {
  const data = artifact?.data;
  const todos = Array.isArray(data)
    ? data
    : data && typeof data === "object" && Array.isArray((data as { todos?: unknown[] }).todos)
      ? (data as { todos: unknown[] }).todos
      : [];

  if (!todos.length) {
    return <EmptyPanel text="还没有 Todo / Plan 产物。" />;
  }

  return (
    <div className="divide-y divide-hairline overflow-hidden rounded-xl border border-hairline bg-white/60">
      {todos.map((todo, index) => {
        const item = todo && typeof todo === "object" ? (todo as Record<string, unknown>) : {};
        const title =
          typeof item.title === "string"
            ? item.title
            : typeof item.content === "string"
              ? item.content
              : typeof todo === "string"
                ? todo
                : `Todo ${index + 1}`;
        const status = typeof item.status === "string" ? item.status : "";
        return (
          <div key={`${title}-${index}`} className="flex items-start gap-3 px-3 py-2.5">
            <div className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-primary-coral" />
            <div className="min-w-0 flex-1">
              <div className="break-words text-[12px] font-medium leading-relaxed text-ink">{title}</div>
              {status && (
                <div className="mt-1 text-[10px] font-bold uppercase tracking-widest text-muted-soft">{status}</div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function EmptyPanel({ text }: { text: string }) {
  return (
    <div className="rounded-xl border border-dashed border-hairline bg-white/40 px-4 py-6 text-center text-[12px] leading-relaxed text-muted-soft">
      {text}
    </div>
  );
}

function RawArtifact({ artifact }: { artifact?: RuntimeArtifact }) {
  if (!artifact) return null;
  const text = artifactText(artifact.data);
  if (!text) return <EmptyPanel text="产物内容为空。" />;
  return (
    <pre className="max-h-[52vh] overflow-auto rounded-xl border border-hairline bg-white/70 p-3 font-mono text-[11px] leading-relaxed text-body">
      {text}
    </pre>
  );
}

export function RuntimeWorkbenchPanel({
  artifacts,
  sessionRef,
  runtimeLabel,
  modelLabel,
  loading,
  onRefresh,
}: RuntimeWorkbenchPanelProps) {
  const diffArtifact = artifacts.find((artifact) => artifact.type === "file_diff");
  const todoArtifact = artifacts.find((artifact) => artifact.type === "todo");
  const [selectedTab, setSelectedTab] = useState<PanelTab | null>(null);
  const tab = selectedTab || (diffArtifact ? "diff" : todoArtifact ? "todo" : "session");

  const tabs = useMemo(
    () => [
      { id: "diff" as const, label: "Diff", icon: FileDiff, count: artifactCount(artifacts, "file_diff") },
      { id: "todo" as const, label: "Todo", icon: ListChecks, count: artifactCount(artifacts, "todo") },
      { id: "all" as const, label: "Artifacts", icon: Archive, count: artifacts.length },
      { id: "session" as const, label: "Session", icon: Layers3, count: sessionRef?.runtime_session_id ? 1 : 0 },
    ],
    [artifacts, sessionRef?.runtime_session_id],
  );

  return (
    <aside className="hidden w-[360px] shrink-0 border-l border-hairline bg-canvas/70 xl:flex xl:flex-col">
      <div className="flex h-14 shrink-0 items-center justify-between border-b border-hairline px-4">
        <div>
          <div className="text-[11px] font-bold uppercase tracking-widest text-muted-soft">Workbench</div>
          <div className="mt-0.5 flex max-w-[230px] items-center gap-2 truncate text-[11px] font-medium text-body">
            {runtimeLabel && (
              <span className="flex min-w-0 items-center gap-1 truncate">
                <Layers3 className="h-3 w-3 shrink-0 text-primary-coral" />
                <span className="truncate">{runtimeLabel}</span>
              </span>
            )}
            {modelLabel && (
              <span className="flex min-w-0 items-center gap-1 truncate">
                <Sparkles className="h-3 w-3 shrink-0 text-muted-soft" />
                <span className="truncate">{modelLabel}</span>
              </span>
            )}
          </div>
        </div>
        <button
          type="button"
          onClick={onRefresh}
          disabled={!onRefresh || loading}
          title="刷新 Runtime 产物"
          className="grid h-8 w-8 cursor-pointer place-items-center rounded-lg text-muted-soft transition hover:bg-stone-100 hover:text-ink active:scale-95 disabled:cursor-not-allowed disabled:opacity-30"
        >
          <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
        </button>
      </div>

      <div className="flex shrink-0 gap-1 border-b border-hairline px-3 py-2">
        {tabs.map((item) => {
          const Icon = item.icon;
          const active = tab === item.id;
          return (
            <button
              key={item.id}
              type="button"
              onClick={() => setSelectedTab(item.id)}
              className={cn(
                "flex h-8 min-w-0 flex-1 cursor-pointer items-center justify-center gap-1.5 rounded-lg px-2 text-[10px] font-bold uppercase tracking-widest transition active:scale-95",
                active ? "bg-white text-ink shadow-sm ring-1 ring-black/[0.03]" : "text-muted-soft hover:bg-stone-100 hover:text-ink",
              )}
            >
              <Icon className="h-3.5 w-3.5 shrink-0" />
              <span className="truncate">{item.label}</span>
              {item.count > 0 && <span className="text-primary-coral">{item.count}</span>}
            </button>
          );
        })}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {tab === "diff" && <DiffReview artifact={diffArtifact} />}

        {tab === "todo" && <TodoList artifact={todoArtifact} />}

        {tab === "all" && (
          artifacts.length ? (
            <div className="space-y-3">
              {artifacts.map((artifact) => (
                <div key={artifact.id} className="space-y-2">
                  <div className="flex items-center justify-between gap-2 text-[10px] font-bold uppercase tracking-widest text-muted-soft">
                    <span className="truncate">{artifact.title || artifact.type}</span>
                    <span>{artifact.status || "ready"}</span>
                  </div>
                  <RawArtifact artifact={artifact} />
                </div>
              ))}
            </div>
          ) : (
            <EmptyPanel text="当前消息还没有 runtime artifact。" />
          )
        )}

        {tab === "session" && (
          <div className="space-y-3">
            <div className="rounded-xl border border-hairline bg-white/60 p-3">
              <div className="text-[10px] font-bold uppercase tracking-widest text-muted-soft">Local Session</div>
              <div className="mt-1 break-all font-mono text-[11px] text-body">
                {sessionRef?.local_session_id || "未绑定"}
              </div>
            </div>
            <div className="rounded-xl border border-hairline bg-white/60 p-3">
              <div className="text-[10px] font-bold uppercase tracking-widest text-muted-soft">Runtime Session</div>
              <div className="mt-1 break-all font-mono text-[11px] text-body">
                {sessionRef?.runtime_session_id || "未创建"}
              </div>
            </div>
            <div className="rounded-xl border border-hairline bg-white/60 p-3">
              <div className="text-[10px] font-bold uppercase tracking-widest text-muted-soft">Workspace</div>
              <div className="mt-1 break-all font-mono text-[11px] text-body">
                {sessionRef?.workspace || "未上报"}
              </div>
            </div>
          </div>
        )}
      </div>
    </aside>
  );
}
