"use client";

import { ChevronDown, Wrench } from "lucide-react";
import { useState } from "react";

import type { ToolStep } from "@/lib/types";
import { cn } from "@/lib/utils";

export function ToolSteps({ steps }: { steps: ToolStep[] }) {
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
        <div className="mt-2 rounded-xl border border-stone-200 bg-stone-100/70 p-3 text-xs leading-relaxed text-stone-600">
          {steps.map((step, index) => (
            <div key={`${step.tool}-${index}`} className="font-mono">
              调用 <span className="text-amber-700">{step.tool}</span> -{" "}
              {JSON.stringify(step.result)}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
