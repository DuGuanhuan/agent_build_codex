"use client";

import { AlertCircle, ChevronDown, FileDiff, ListChecks } from "lucide-react";
import { useState } from "react";

import type { RuntimeArtifact } from "@/lib/types";
import { cn } from "@/lib/utils";

function artifactIcon(type: string) {
  if (type === "file_diff") return FileDiff;
  if (type === "todo") return ListChecks;
  return AlertCircle;
}

function artifactLabel(artifact: RuntimeArtifact) {
  if (artifact.title) return artifact.title;
  if (artifact.type === "file_diff") return "Workspace Diff";
  if (artifact.type === "todo") return "Todo / Plan";
  return artifact.type;
}

function artifactText(data: unknown) {
  if (typeof data === "string") return data;
  if (data == null) return "";
  return JSON.stringify(data, null, 2);
}

function TodoPreview({ data }: { data: unknown }) {
  const todos = Array.isArray(data)
    ? data
    : data && typeof data === "object" && Array.isArray((data as { todos?: unknown[] }).todos)
      ? (data as { todos: unknown[] }).todos
      : null;

  if (!todos) return null;

  return (
    <div className="space-y-1.5">
      {todos.slice(0, 8).map((todo, index) => {
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
          <div key={`${title}-${index}`} className="flex items-center justify-between gap-3 text-[12px]">
            <span className="min-w-0 truncate text-body">{title}</span>
            {status && <span className="shrink-0 text-[10px] font-bold uppercase tracking-widest text-muted-soft">{status}</span>}
          </div>
        );
      })}
    </div>
  );
}

export function RuntimeArtifacts({ artifacts }: { artifacts: RuntimeArtifact[] }) {
  const [openArtifactId, setOpenArtifactId] = useState<string | null>(artifacts[0]?.id || null);

  if (!artifacts.length) return null;

  return (
    <section className="mt-1.5 space-y-2">
      <div className="text-[10px] font-bold uppercase tracking-[0.14em] text-muted-soft">
        Runtime Artifacts
      </div>
      <div className="overflow-hidden rounded-2xl border border-hairline bg-white/50">
        {artifacts.map((artifact, index) => {
          const Icon = artifactIcon(artifact.type);
          const open = openArtifactId === artifact.id;
          const text = artifactText(artifact.data);
          const isError = artifact.status === "error" || artifact.type === "diagnostic";
          return (
            <div key={artifact.id} className={cn(index > 0 && "border-t border-hairline")}>
              <button
                type="button"
                onClick={() => setOpenArtifactId(open ? null : artifact.id)}
                className="flex w-full cursor-pointer items-center justify-between gap-3 px-3 py-2.5 text-left transition hover:bg-white/80"
              >
                <span className="flex min-w-0 items-center gap-2">
                  <span
                    className={cn(
                      "grid h-6 w-6 shrink-0 place-items-center rounded-lg",
                      isError ? "bg-rose-50 text-rose-500" : "bg-surface-soft text-muted-soft",
                    )}
                  >
                    <Icon className="h-3.5 w-3.5" />
                  </span>
                  <span className="min-w-0 truncate text-[12px] font-bold uppercase tracking-wider text-ink">
                    {artifactLabel(artifact)}
                  </span>
                </span>
                <ChevronDown className={cn("h-3.5 w-3.5 text-muted-soft transition", open && "rotate-180")} />
              </button>

              {open && (
                <div className="space-y-3 border-t border-hairline bg-stone-50/40 p-3">
                  {artifact.type === "todo" && <TodoPreview data={artifact.data} />}
                  {text && (
                    <pre className="max-h-80 overflow-auto rounded-xl border border-hairline bg-white p-3 font-mono text-[11px] leading-relaxed text-body">
                      {text}
                    </pre>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
