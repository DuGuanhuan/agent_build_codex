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

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpen(false);
      }
    }

    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, []);

  return (
    <div ref={pickerRef} className="relative">
      <button
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="grid min-h-11 w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-x-2 rounded-2xl border border-stone-200 bg-white/90 px-3 py-2 text-left shadow-sm transition hover:border-amber-300 hover:shadow-md focus:outline-none focus:ring-4 focus:ring-amber-500/10 md:min-h-14"
      >
        <span className="text-[11px] font-bold uppercase leading-none text-stone-400">
          {selectedModel ? providerLabel(selectedModel.provider) : "模型"}
        </span>
        <ChevronDown
          className={cn(
            "col-start-2 row-span-2 h-4 w-4 text-stone-400 transition",
            open && "rotate-180",
          )}
        />
        <span className="min-w-0 truncate text-sm font-bold leading-tight text-stone-950">
          {selectedModel?.label || "选择模型"}
        </span>
      </button>

      {open ? (
        <div
          role="listbox"
          aria-label="选择模型"
          className="absolute bottom-[calc(100%+10px)] left-0 z-30 w-[min(380px,calc(100vw-32px))] rounded-2xl border border-stone-200 bg-white/95 p-2 shadow-2xl backdrop-blur-xl"
        >
          <div className="flex items-center justify-between px-1 pb-2 pt-1 text-sm font-bold text-stone-950">
            <span>选择本次对话模型</span>
            <span className="text-xs font-semibold text-stone-400">
              {models.filter((model) => model.available).length}/{models.length} 可用
            </span>
          </div>
          <div className="grid gap-2">
            {models.map((model) => {
              const selected = model.id === selectedModelId;
              const mode = model.thinking === "enabled" ? "Thinking" : "Chat";

              return (
                <button
                  key={model.id}
                  type="button"
                  role="option"
                  aria-selected={selected}
                  disabled={!model.available}
                  onClick={() => {
                    onSelect(model.id);
                    setOpen(false);
                  }}
                  className={cn(
                    "grid gap-1 rounded-xl border border-stone-100 bg-white px-3 py-3 text-left transition hover:-translate-y-0.5 hover:border-amber-300 hover:bg-amber-50/50",
                    selected && "border-amber-400 bg-amber-50",
                    !model.available && "cursor-not-allowed opacity-50 hover:translate-y-0 hover:bg-white",
                  )}
                >
                  <span className="flex items-start justify-between gap-3">
                    <span className="font-bold leading-tight text-stone-950">{model.label}</span>
                    {selected ? <Check className="h-4 w-4 shrink-0 text-amber-700" /> : null}
                  </span>
                  <span className="flex flex-wrap gap-1.5 text-[11px] font-bold text-stone-500">
                    <span className="rounded-full bg-stone-100 px-2 py-0.5">
                      {providerLabel(model.provider)}
                    </span>
                    <span className="rounded-full bg-stone-100 px-2 py-0.5">
                      {mode}
                      {!model.available ? " · 未配置 key" : ""}
                    </span>
                  </span>
                  <span className="text-xs leading-relaxed text-stone-600">{model.description}</span>
                </button>
              );
            })}
          </div>
        </div>
      ) : null}
    </div>
  );
}
