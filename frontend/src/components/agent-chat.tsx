"use client";

import { ArrowUp, Calculator, Clock3, Layers3, Loader2 } from "lucide-react";
import { FormEvent, useEffect, useRef, useState } from "react";

import { MarkdownMessage } from "@/components/markdown-message";
import { ModelPicker } from "@/components/model-picker";
import { ToolSteps } from "@/components/tool-steps";
import type { AgentResponse, ModelOption, ToolStep } from "@/lib/types";
import { cn } from "@/lib/utils";

type DisplayMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  steps?: ToolStep[];
};

const suggestions = [
  {
    icon: Clock3,
    label: "现在几点了？",
    prompt: "现在几点了？",
  },
  {
    icon: Calculator,
    label: "帮我算 128 x 37",
    prompt: "帮我算 128 * 37",
  },
  {
    icon: Calculator,
    label: "π 精确到 10 位",
    prompt: "π 的值精确到小数点后 10 位是多少？",
  },
  {
    icon: Layers3,
    label: "写一首编程俳句",
    prompt: "用中文写一首关于编程的俳句",
  },
];

function makeId(prefix: string) {
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function AgentChat() {
  const [models, setModels] = useState<ModelOption[]>([]);
  const [selectedModelId, setSelectedModelId] = useState("");
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [input, setInput] = useState("");
  const [pending, setPending] = useState(false);
  const [loadError, setLoadError] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    async function loadModels() {
      try {
        const response = await fetch("/api/models", { cache: "no-store" });
        const data = (await response.json()) as { models: ModelOption[]; default: string };
        if (!response.ok || !Array.isArray(data.models)) {
          throw new Error("模型列表加载失败");
        }

        const savedModelId = window.localStorage.getItem("agent:model");
        const availableModels = data.models.filter((model) => model.available);
        const nextModelId =
          availableModels.find((model) => model.id === savedModelId)?.id ||
          availableModels.find((model) => model.id === data.default)?.id ||
          availableModels[0]?.id ||
          data.default ||
          data.models[0]?.id ||
          "";

        setModels(data.models);
        setSelectedModelId(nextModelId);
      } catch (error) {
        setLoadError(error instanceof Error ? error.message : "模型列表加载失败");
      }
    }

    loadModels();
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [messages, pending]);

  function selectModel(modelId: string) {
    setSelectedModelId(modelId);
    window.localStorage.setItem("agent:model", modelId);
  }

  async function sendMessage(text: string) {
    const content = text.trim();
    if (!content || pending) {
      return;
    }

    const nextUserMessage: DisplayMessage = {
      id: makeId("user"),
      role: "user",
      content,
    };

    const nextMessages = [...messages, nextUserMessage];
    setMessages(nextMessages);
    setInput("");
    setPending(true);

    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 60000);

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          model: selectedModelId,
          messages: nextMessages.map((message) => ({
            role: message.role,
            content: message.content,
          })),
        }),
        signal: controller.signal,
      });

      const data = (await response.json()) as AgentResponse | { error?: string };
      const errorMessage = "error" in data ? data.error : undefined;
      if (!response.ok || errorMessage) {
        throw new Error(errorMessage || `请求失败 (HTTP ${response.status})`);
      }

      const agentData = data as AgentResponse;

      setMessages((current) => [
        ...current,
        {
          id: makeId("assistant"),
          role: "assistant",
          content: agentData.answer,
          steps: agentData.steps || [],
        },
      ]);
    } catch (error) {
      const message = error instanceof Error && error.name === "AbortError"
        ? "请求超时，请稍后重试"
        : error instanceof Error
          ? error.message
          : "请求失败";

      setMessages((current) => [
        ...current,
        {
          id: makeId("assistant"),
          role: "assistant",
          content: `出错了：${message}`,
        },
      ]);
    } finally {
      window.clearTimeout(timeout);
      setPending(false);
    }
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    sendMessage(input);
  }

  return (
    <div className="flex min-h-dvh flex-col bg-stone-100 text-stone-950">
      <header className="sticky top-0 z-20 flex h-14 items-center justify-between border-b border-stone-200 bg-stone-100/85 px-4 backdrop-blur-xl md:px-6">
        <div className="flex items-center gap-2.5">
          <div className="grid h-7 w-7 place-items-center rounded-lg text-amber-600">
            <Layers3 className="h-5 w-5" />
          </div>
          <span className="font-bold tracking-tight">手搓 Agent</span>
        </div>
        <div className="hidden items-center gap-2 md:flex">
          <span className="inline-flex items-center gap-1.5 rounded-full border border-stone-200 px-3 py-1 text-xs font-medium text-stone-500">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
            current_time
          </span>
          <span className="inline-flex items-center gap-1.5 rounded-full border border-stone-200 px-3 py-1 text-xs font-medium text-stone-500">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
            calculator
          </span>
        </div>
      </header>

      <main className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto flex min-h-full w-full max-w-3xl flex-col px-4 pb-36 pt-6 md:px-6">
          {messages.length === 0 ? (
            <section className="flex flex-1 flex-col items-center justify-center py-16 text-center">
              <Layers3 className="mb-6 h-12 w-12 text-amber-600" />
              <h1 className="text-3xl font-bold tracking-tight md:text-4xl">有什么可以帮你的？</h1>
              <p className="mt-3 max-w-md text-sm leading-7 text-stone-600">
                我是一个轻量级手写 Agent，可以直接聊天，也能调用时间和计算工具。
              </p>
              <div className="mt-8 grid w-full max-w-lg grid-cols-1 gap-3 md:grid-cols-2">
                {suggestions.map((suggestion) => {
                  const Icon = suggestion.icon;
                  return (
                    <button
                      key={suggestion.label}
                      type="button"
                      disabled={pending}
                      onClick={() => sendMessage(suggestion.prompt)}
                      className="flex items-center gap-3 rounded-xl border border-stone-200 bg-white px-4 py-3 text-left text-sm font-medium text-stone-600 shadow-sm transition hover:-translate-y-0.5 hover:border-amber-300 hover:text-stone-950 hover:shadow-md disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      <Icon className="h-4 w-4 text-stone-400" />
                      {suggestion.label}
                    </button>
                  );
                })}
              </div>
            </section>
          ) : (
            <div className="grid gap-4">
              {messages.map((message) => (
                <article
                  key={message.id}
                  className={cn(
                    "max-w-full",
                    message.role === "user"
                      ? "justify-self-end rounded-2xl rounded-br-md border border-stone-200 bg-stone-50 px-4 py-3 text-sm leading-7 shadow-sm md:max-w-[85%]"
                      : "grid grid-cols-[28px_minmax(0,1fr)] gap-3 py-3",
                  )}
                >
                  {message.role === "user" ? (
                    <span className="whitespace-pre-wrap break-words">{message.content}</span>
                  ) : (
                    <>
                      <div className="mt-1 grid h-7 w-7 place-items-center rounded-lg bg-amber-600 text-white">
                        <Layers3 className="h-4 w-4" />
                      </div>
                      <div className="min-w-0">
                        <MarkdownMessage content={message.content} />
                        <ToolSteps steps={message.steps || []} />
                      </div>
                    </>
                  )}
                </article>
              ))}

              {pending ? (
                <article className="grid grid-cols-[28px_minmax(0,1fr)] gap-3 py-3">
                  <div className="mt-1 grid h-7 w-7 place-items-center rounded-lg bg-amber-600 text-white">
                    <Layers3 className="h-4 w-4" />
                  </div>
                  <div className="flex items-center gap-2 py-1 text-sm text-stone-500">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Agent 思考中...
                  </div>
                </article>
              ) : null}
            </div>
          )}
          <div ref={scrollRef} />
        </div>
      </main>

      <div className="sticky bottom-0 z-20 bg-gradient-to-b from-transparent via-stone-100 to-stone-100 px-3 pb-3 pt-8 md:px-6 md:pb-4">
        <div className="mx-auto grid w-full max-w-[968px] grid-cols-1 items-end gap-2 md:grid-cols-[190px_minmax(0,768px)]">
          <ModelPicker models={models} selectedModelId={selectedModelId} onSelect={selectModel} />
          <form
            onSubmit={onSubmit}
            className="relative rounded-2xl border border-stone-200 bg-white shadow-lg transition focus-within:border-stone-300 focus-within:ring-4 focus-within:ring-amber-500/10"
          >
            <textarea
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  event.currentTarget.form?.requestSubmit();
                }
              }}
              rows={1}
              placeholder={loadError || "给 Agent 发消息..."}
              className="block max-h-48 min-h-14 w-full resize-none rounded-2xl bg-transparent px-5 py-4 pr-16 text-sm leading-6 outline-none placeholder:text-stone-400"
            />
            <button
              type="submit"
              disabled={!input.trim() || pending || !selectedModelId}
              aria-label="发送"
              className="absolute bottom-2.5 right-2.5 grid h-9 w-9 place-items-center rounded-xl bg-stone-950 text-white transition hover:scale-105 hover:bg-stone-800 disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:scale-100"
            >
              <ArrowUp className="h-4 w-4" />
            </button>
          </form>
        </div>
        <p className="mt-2 text-center text-xs text-stone-400">Agent 可能会犯错，请核实重要信息。</p>
      </div>
    </div>
  );
}
