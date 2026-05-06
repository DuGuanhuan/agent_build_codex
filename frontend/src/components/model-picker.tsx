"use client";

import { Check, ChevronDown } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";
import type { ModelOption } from "@/lib/types";

type ModelPickerProps = {
  models: ModelOption[];
  selectedModelId: string;
  onSelect: (modelId: string) => void;
};

const providerLabels: Record<string, string> = {
  zhipu: "智谱",
  deepseek: "DeepSeek",
  wanqing: "万擎",
  anthropic: "Anthropic",
};

function providerLabel(provider: string) {
  return providerLabels[provider] || provider || "模型";
}

export function ModelPicker({ models, selectedModelId, onSelect }: ModelPickerProps) {
  const [open, setOpen] = useState(false);
  const pickerRef = useRef<HTMLDivElement>(null);
  const selectedModel = models.find((model) => model.id === selectedModelId);

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
        <span className="text-[12px] font-bold text-muted uppercase tracking-widest">
          {selectedModel?.label || "Select Model"}
        </span>
        <ChevronDown className={cn("h-3 w-3 text-muted-soft transition", open && "rotate-180")} />
      </button>

      {open && (
        <div className="absolute bottom-full left-0 z-50 mb-2 w-72 rounded-2xl border border-hairline bg-white p-1.5 shadow-2xl shadow-black/10 animate-in fade-in slide-in-from-bottom-2">
          <div className="px-2 py-1.5 text-[10px] font-bold text-muted-soft uppercase tracking-wider">
            Available Models
          </div>
          <div className="grid max-h-80 gap-0.5 overflow-y-auto">
            {models.map((model) => {
              const selected = model.id === selectedModelId;
              return (
                <button
                  key={model.id}
                  type="button"
                  disabled={!model.available}
                  onClick={() => {
                    onSelect(model.id);
                    setOpen(false);
                  }}
                  className={cn(
                    "group flex cursor-pointer items-center justify-between rounded-xl px-3 py-2 text-left transition active:scale-[0.98]",
                    selected ? "bg-surface-soft" : "hover:bg-stone-50",
                    !model.available && "cursor-not-allowed opacity-40"
                  )}
                >
                  <div className="flex flex-col min-w-0">
                    <span className="truncate text-sm font-semibold text-ink">{model.label}</span>
                    <span className="text-[10px] font-bold text-muted-soft uppercase tracking-tight">
                      {providerLabel(model.provider)}
                    </span>
                  </div>
                  {selected && <Check className="h-3.5 w-3.5 text-primary-coral" />}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
