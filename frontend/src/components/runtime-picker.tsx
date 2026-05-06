"use client";

import { Bot, Check, ChevronDown } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import type { RuntimeOption } from "@/lib/types";
import { cn } from "@/lib/utils";

type RuntimePickerProps = {
  runtimes: RuntimeOption[];
  selectedRuntimeId: string;
  onSelect: (runtimeId: string) => void;
};

function capabilityLabel(runtime: RuntimeOption) {
  const labels = [];
  if (runtime.capabilities.toolEvents) labels.push("tools");
  if (runtime.capabilities.fileRead) labels.push("read");
  if (runtime.capabilities.fileWrite) labels.push("write");
  if (runtime.capabilities.shell) labels.push("shell");
  return labels.slice(0, 3).join(" · ") || "chat";
}

export function RuntimePicker({ runtimes, selectedRuntimeId, onSelect }: RuntimePickerProps) {
  const [open, setOpen] = useState(false);
  const pickerRef = useRef<HTMLDivElement>(null);
  const selectedRuntime = runtimes.find((runtime) => runtime.id === selectedRuntimeId);

  useEffect(() => {
    function onPointerDown(event: PointerEvent) {
      if (!pickerRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, []);

  return (
    <div ref={pickerRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex cursor-pointer items-center gap-1.5 rounded-lg px-2 py-1 text-left transition hover:bg-stone-100 active:scale-95"
      >
        <Bot className="h-3.5 w-3.5 text-primary-coral" />
        <span className="text-[12px] font-bold text-muted uppercase tracking-widest">
          {selectedRuntime?.label || "Agent"}
        </span>
        <ChevronDown className={cn("h-3 w-3 text-muted-soft transition", open && "rotate-180")} />
      </button>

      {open && (
        <div className="absolute bottom-full left-0 z-50 mb-2 w-80 rounded-2xl border border-hairline bg-white p-1.5 shadow-2xl shadow-black/10 animate-in fade-in slide-in-from-bottom-2">
          <div className="px-2 py-1.5 text-[10px] font-bold text-muted-soft uppercase tracking-wider">
            Agent Runtime
          </div>
          <div className="grid max-h-80 gap-0.5 overflow-y-auto">
            {runtimes.map((runtime) => {
              const selected = runtime.id === selectedRuntimeId;
              return (
                <button
                  key={runtime.id}
                  type="button"
                  disabled={!runtime.available}
                  onClick={() => {
                    onSelect(runtime.id);
                    setOpen(false);
                  }}
                  title={!runtime.available ? runtime.unavailable_reason : runtime.description}
                  className={cn(
                    "group flex cursor-pointer items-center justify-between gap-3 rounded-xl px-3 py-2 text-left transition active:scale-[0.98]",
                    selected ? "bg-surface-soft" : "hover:bg-stone-50",
                    !runtime.available && "cursor-not-allowed opacity-40",
                  )}
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex min-w-0 items-center gap-2">
                      <span className="truncate text-sm font-semibold text-ink">{runtime.label}</span>
                      {runtime.version && (
                        <span className="shrink-0 rounded-full bg-stone-100 px-1.5 py-0.5 text-[9px] font-bold text-muted-soft">
                          {runtime.version}
                        </span>
                      )}
                    </div>
                    <span className="mt-0.5 block truncate text-[10px] font-bold text-muted-soft uppercase tracking-tight">
                      {runtime.available ? capabilityLabel(runtime) : runtime.unavailable_reason || "unavailable"}
                    </span>
                  </div>
                  {selected && <Check className="h-3.5 w-3.5 shrink-0 text-primary-coral" />}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
