"use client";

import {
  ArrowUp,
  Calculator,
  Check,
  Clock3,
  Layers3,
  Loader2,
  MessageSquare,
  Pencil,
  Plus,
  Archive,
  Square,
  Trash2,
  X,
} from "lucide-react";
import { FormEvent, useCallback, useEffect, useRef, useState } from "react";

import { MarkdownMessage } from "@/components/markdown-message";
import { ModelPicker } from "@/components/model-picker";
import { ToolSteps } from "@/components/tool-steps";
import type { ModelOption, ToolOption, ToolStep } from "@/lib/types";
import { cn } from "@/lib/utils";

type DisplayMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  model?: string;
  steps?: ToolStep[];
  status?: "streaming" | "done" | "error" | "stopped";
};

type ChatSession = {
  id: string;
  title: string;
  createdAt: number;
  updatedAt: number;
  modelId: string;
  messages: DisplayMessage[];
  summary?: string;
  summaryUpdatedAt?: number;
  summarizedMessageCount?: number;
  summaryTriggerRatio?: number;
};

type StreamEvent = {
  event: string;
  data: Record<string, unknown>;
};

type ContextEstimate = {
  model: string;
  estimator: "approximate" | string;
  input_tokens: number;
  context_window_tokens: number;
  reserved_output_tokens: number;
  available_input_tokens: number;
  ratio: number;
};

const SESSIONS_STORAGE_KEY = "agent:sessions";
const ACTIVE_SESSION_STORAGE_KEY = "agent:active-session-id";
const MAX_SESSIONS = 24;
const MAX_STORED_MESSAGES = 80;
const SUMMARY_TRIGGER_RATIO = 0.75;
const SUMMARY_KEEP_RECENT_MESSAGES = 8;
const EMPTY_MESSAGES: DisplayMessage[] = [];

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

function makeSession(modelId = ""): ChatSession {
  const now = Date.now();
  return {
    id: makeId("session"),
    title: "新会话",
    createdAt: now,
    updatedAt: now,
    modelId,
    messages: [],
    summary: "",
    summaryUpdatedAt: undefined,
    summarizedMessageCount: 0,
    summaryTriggerRatio: SUMMARY_TRIGGER_RATIO,
  };
}

function titleFromMessage(content: string) {
  const title = content.trim().replace(/\s+/g, " ").slice(0, 28);
  return title || "新会话";
}

function normalizeSession(value: unknown): ChatSession | null {
  if (!value || typeof value !== "object") {
    return null;
  }

  const session = value as Partial<ChatSession>;
  if (typeof session.id !== "string") {
    return null;
  }

  return {
    id: session.id,
    title: typeof session.title === "string" && session.title.trim() ? session.title : "新会话",
    createdAt: typeof session.createdAt === "number" ? session.createdAt : Date.now(),
    updatedAt: typeof session.updatedAt === "number" ? session.updatedAt : Date.now(),
    modelId: typeof session.modelId === "string" ? session.modelId : "",
    messages: Array.isArray(session.messages) ? session.messages.slice(-MAX_STORED_MESSAGES) : [],
    summary: typeof session.summary === "string" ? session.summary : "",
    summaryUpdatedAt: typeof session.summaryUpdatedAt === "number" ? session.summaryUpdatedAt : undefined,
    summarizedMessageCount:
      typeof session.summarizedMessageCount === "number" ? Math.max(0, session.summarizedMessageCount) : 0,
    summaryTriggerRatio:
      typeof session.summaryTriggerRatio === "number"
        ? Math.max(0.5, Math.min(1, session.summaryTriggerRatio))
        : SUMMARY_TRIGGER_RATIO,
  };
}

function loadStoredSessions() {
  try {
    const raw = window.localStorage.getItem(SESSIONS_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(parsed)) {
      return [];
    }

    return parsed.flatMap((item) => {
      const session = normalizeSession(item);
      return session ? [session] : [];
    });
  } catch {
    return [];
  }
}

function readStoredActiveSessionModelId() {
  const sessions = loadStoredSessions();
  const activeSessionId = window.localStorage.getItem(ACTIVE_SESSION_STORAGE_KEY);
  return sessions.find((session) => session.id === activeSessionId)?.modelId || "";
}

function eligibleContextMessages(messages: DisplayMessage[]) {
  return messages
    .filter((message) => {
      if (!message.content.trim()) {
        return false;
      }
      if (message.role === "assistant" && message.status && !["done", "streaming"].includes(message.status)) {
        return false;
      }
      return message.role === "user" || message.role === "assistant";
    })
    .map((message) => ({
      role: message.role,
      content: message.content,
    }));
}

function buildContextMessages(session: ChatSession, nextMessages = session.messages) {
  const eligibleMessages = eligibleContextMessages(nextMessages);
  const summarizedCount = Math.min(session.summarizedMessageCount || 0, eligibleMessages.length);
  const recentMessages = eligibleMessages.slice(summarizedCount);

  if (!session.summary) {
    return eligibleMessages;
  }

  return [
    {
      role: "user" as const,
      content: `以下是此前会话摘要，用于延续上下文：\n${session.summary}`,
    },
    ...recentMessages,
  ];
}

function contextUsage(session?: ChatSession, estimate?: ContextEstimate | null, estimateError = "") {
  const threshold = session?.summaryTriggerRatio || SUMMARY_TRIGGER_RATIO;
  if (estimate) {
    return {
      usedTokens: estimate.input_tokens,
      limitTokens: estimate.context_window_tokens,
      availableTokens: estimate.available_input_tokens,
      reservedOutputTokens: estimate.reserved_output_tokens,
      ratio: Math.min(1, estimate.ratio),
      threshold,
      estimator: estimate.estimator,
      loading: false,
      error: "",
    };
  }

  if (!session) {
    return {
      usedTokens: 0,
      limitTokens: 0,
      availableTokens: 0,
      reservedOutputTokens: 0,
      ratio: 0,
      threshold,
      estimator: "approximate",
      loading: false,
      error: "",
    };
  }

  return {
    usedTokens: 0,
    limitTokens: 0,
    availableTokens: 0,
    reservedOutputTokens: 0,
    ratio: 0,
    threshold,
    estimator: "approximate",
    loading: !estimateError,
    error: estimateError,
  };
}

const summaryThresholdOptions = [
  { label: "60%", value: 0.6 },
  { label: "75%", value: 0.75 },
  { label: "90%", value: 0.9 },
];

function formatTokens(tokens: number) {
  if (!Number.isFinite(tokens) || tokens <= 0) {
    return "0";
  }
  if (tokens >= 1_000_000) {
    const value = tokens / 1_000_000;
    return `${value >= 10 ? value.toFixed(0) : value.toFixed(1)}M`;
  }
  if (tokens >= 1_000) {
    const value = tokens / 1_000;
    return `${value >= 10 ? value.toFixed(0) : value.toFixed(1)}K`;
  }
  return String(Math.round(tokens));
}

async function readJsonResponse<T>(response: Response, fallbackMessage: string): Promise<T> {
  const text = await response.text();
  if (!text.trim()) {
    throw new Error(fallbackMessage);
  }

  try {
    return JSON.parse(text) as T;
  } catch {
    throw new Error(fallbackMessage);
  }
}

function parseSseFrames(buffer: string): { events: StreamEvent[]; rest: string } {
  const parts = buffer.split("\n\n");
  const rest = parts.pop() || "";
  const events = parts.flatMap((part) => {
    let event = "message";
    const dataLines: string[] = [];

    for (const line of part.split("\n")) {
      if (line.startsWith("event:")) {
        event = line.slice("event:".length).trim();
      } else if (line.startsWith("data:")) {
        dataLines.push(line.slice("data:".length).trimStart());
      }
    }

    if (!dataLines.length) {
      return [];
    }

    try {
      return [{ event, data: JSON.parse(dataLines.join("\n")) as Record<string, unknown> }];
    } catch {
      return [{ event: "error", data: { message: "流式响应解析失败" } }];
    }
  });

  return { events, rest };
}

function upsertStep(steps: ToolStep[], step: ToolStep) {
  const stepId = step.id;
  const index = steps.findIndex((item) => item.id === stepId);
  if (index === -1) {
    return [...steps, step];
  }

  return steps.map((item, itemIndex) => (itemIndex === index ? { ...item, ...step } : item));
}

export function AgentChat() {
  const [models, setModels] = useState<ModelOption[]>([]);
  const [tools, setTools] = useState<ToolOption[]>([]);
  const [selectedModelId, setSelectedModelId] = useState("");
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState("");
  const [sessionsLoaded, setSessionsLoaded] = useState(false);
  const [editingSessionId, setEditingSessionId] = useState("");
  const [editingTitle, setEditingTitle] = useState("");
  const [input, setInput] = useState("");
  const [pending, setPending] = useState(false);
  const [summarizing, setSummarizing] = useState(false);
  const [contextEstimateState, setContextEstimateState] = useState<{
    sessionId: string;
    estimate?: ContextEstimate;
    error?: string;
  } | null>(null);
  const [loadError, setLoadError] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const sessionsRef = useRef<ChatSession[]>([]);
  const activeSession = sessions.find((session) => session.id === activeSessionId);
  const messages = activeSession?.messages ?? EMPTY_MESSAGES;
  const contextEstimate =
    contextEstimateState?.sessionId === activeSessionId ? contextEstimateState.estimate || null : null;
  const contextEstimateError =
    contextEstimateState?.sessionId === activeSessionId ? contextEstimateState.error || "" : "";
  const activeContextUsage = contextUsage(activeSession, contextEstimate, contextEstimateError);

  function updateActiveSession(updater: (session: ChatSession) => ChatSession) {
    setSessions((current) =>
      current.map((session) =>
        session.id === activeSessionId
          ? {
              ...updater(session),
              updatedAt: Date.now(),
            }
          : session,
      ),
    );
  }

  useEffect(() => {
    sessionsRef.current = sessions;
  }, [sessions]);

  function setActiveMessages(updater: DisplayMessage[] | ((messages: DisplayMessage[]) => DisplayMessage[])) {
    updateActiveSession((session) => {
      const nextMessages =
        typeof updater === "function" ? updater(session.messages) : updater;
      return {
        ...session,
        messages: nextMessages.slice(-MAX_STORED_MESSAGES),
      };
    });
  }

  const estimateSessionContext = useCallback(async (session: ChatSession, nextMessages = session.messages, signal?: AbortSignal) => {
    const response = await fetch("/api/context/estimate", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        model: session.modelId || selectedModelId,
        messages: buildContextMessages(session, nextMessages),
      }),
      signal,
    });
    const data = await readJsonResponse<ContextEstimate | { error?: string }>(response, "上下文估算失败");
    if (!response.ok || ("error" in data && data.error)) {
      throw new Error("error" in data && data.error ? data.error : "上下文估算失败");
    }
    if (!("input_tokens" in data)) {
      throw new Error("上下文估算失败");
    }
    return data;
  }, [selectedModelId]);

  useEffect(() => {
    async function loadModels() {
      try {
        const response = await fetch("/api/models", { cache: "no-store" });
        const data = await readJsonResponse<{ models?: ModelOption[]; default?: string; error?: string }>(
          response,
          "模型列表加载失败",
        );
        if (data.error) {
          throw new Error(data.error);
        }
        if (!response.ok || !Array.isArray(data.models)) {
          throw new Error("模型列表加载失败");
        }

        const savedModelId = readStoredActiveSessionModelId() || window.localStorage.getItem("agent:model");
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
    async function loadSessions() {
      await Promise.resolve();
      const storedSessions = loadStoredSessions();
      const nextSessions = storedSessions.length ? storedSessions : [makeSession()];
      const savedActiveSessionId = window.localStorage.getItem(ACTIVE_SESSION_STORAGE_KEY);
      const nextActiveSessionId =
        nextSessions.find((session) => session.id === savedActiveSessionId)?.id || nextSessions[0].id;

      setSessions(nextSessions);
      setActiveSessionId(nextActiveSessionId);
      setSessionsLoaded(true);
    }

    loadSessions();
  }, []);

  useEffect(() => {
    if (!sessionsLoaded) {
      return;
    }

    window.localStorage.setItem(SESSIONS_STORAGE_KEY, JSON.stringify(sessions.slice(0, MAX_SESSIONS)));
    window.localStorage.setItem(ACTIVE_SESSION_STORAGE_KEY, activeSessionId);
  }, [activeSessionId, sessions, sessionsLoaded]);

  useEffect(() => {
    async function loadTools() {
      try {
        const response = await fetch("/api/tools", { cache: "no-store" });
        const data = await readJsonResponse<{ tools?: ToolOption[] }>(response, "工具列表加载失败");
        if (response.ok && Array.isArray(data.tools)) {
          setTools(data.tools);
        }
      } catch {
        setTools([]);
      }
    }

    loadTools();
  }, []);

  useEffect(() => {
    if (!activeSession || !selectedModelId) {
      return;
    }
    if (pending) {
      return;
    }

    const controller = new AbortController();
    estimateSessionContext(activeSession, activeSession.messages, controller.signal)
      .then((estimate) => setContextEstimateState({ sessionId: activeSession.id, estimate }))
      .catch((error) => {
        if (error instanceof Error && error.name === "AbortError") {
          return;
        }
        setContextEstimateState({
          sessionId: activeSession.id,
          error: error instanceof Error ? error.message : "上下文估算失败",
        });
      });

    return () => controller.abort();
  }, [activeSession, estimateSessionContext, pending, selectedModelId]);

  useEffect(() => {
    scrollRef.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [messages, pending]);

  function selectModel(modelId: string) {
    setSelectedModelId(modelId);
    window.localStorage.setItem("agent:model", modelId);
    if (activeSessionId) {
      updateActiveSession((session) => ({ ...session, modelId }));
    }
  }

  function createSession() {
    if (pending) {
      return;
    }

    const session = makeSession(selectedModelId);
    setSessions((current) => [session, ...current].slice(0, MAX_SESSIONS));
    setActiveSessionId(session.id);
    setInput("");
  }

  function switchSession(sessionId: string) {
    if (pending || sessionId === activeSessionId) {
      return;
    }

    const session = sessions.find((item) => item.id === sessionId);
    if (!session) {
      return;
    }

    setActiveSessionId(sessionId);
    if (session.modelId) {
      setSelectedModelId(session.modelId);
    }
    setInput("");
  }

  function deleteSession(sessionId: string) {
    if (pending) {
      return;
    }

    const remaining = sessions.filter((session) => session.id !== sessionId);
    if (remaining.length) {
      setSessions(remaining);
      if (sessionId === activeSessionId) {
        setActiveSessionId(remaining[0].id);
        setSelectedModelId(remaining[0].modelId || selectedModelId);
      }
      return;
    }

    const fallback = makeSession(selectedModelId);
    setSessions([fallback]);
    setActiveSessionId(fallback.id);
  }

  function updateSummaryTriggerRatio(ratio: number) {
    if (!activeSessionId || Number.isNaN(ratio)) {
      return;
    }

    updateActiveSession((session) => ({ ...session, summaryTriggerRatio: ratio }));
  }

  function startRenameSession(session: ChatSession) {
    setEditingSessionId(session.id);
    setEditingTitle(session.title);
  }

  function finishRenameSession() {
    const nextTitle = editingTitle.trim();
    if (!editingSessionId || !nextTitle) {
      setEditingSessionId("");
      setEditingTitle("");
      return;
    }

    setSessions((current) =>
      current.map((session) =>
        session.id === editingSessionId
          ? { ...session, title: nextTitle.slice(0, 40), updatedAt: Date.now() }
          : session,
      ),
    );
    setEditingSessionId("");
    setEditingTitle("");
  }

  function stopGeneration() {
    abortRef.current?.abort();
  }

  async function summarizeSession(sessionId: string, mode: "auto" | "manual", messagesOverride?: DisplayMessage[]) {
    const session = sessionsRef.current.find((item) => item.id === sessionId);
    if (!session || summarizing) {
      return;
    }

    const eligibleMessages = eligibleContextMessages(messagesOverride || session.messages);
    const compressUntil = Math.max(0, eligibleMessages.length - SUMMARY_KEEP_RECENT_MESSAGES);
    if (compressUntil <= (session.summarizedMessageCount || 0)) {
      return;
    }

    const messagesToSummarize = eligibleMessages.slice(session.summarizedMessageCount || 0, compressUntil);
    if (!messagesToSummarize.length) {
      return;
    }

    setSummarizing(true);
    try {
      const response = await fetch("/api/summarize", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          model: session.modelId || selectedModelId,
          summary: session.summary || "",
          messages: messagesToSummarize,
        }),
      });
      const data = await readJsonResponse<{ summary?: string; error?: string | { message?: string } }>(
        response,
        "摘要生成失败",
      );
      const rawError = data.error;
      const errorMessage = typeof rawError === "string" ? rawError : rawError?.message;
      if (!response.ok || errorMessage || !data.summary) {
        throw new Error(errorMessage || "摘要生成失败");
      }

      setSessions((current) =>
        current.map((item) =>
          item.id === sessionId
            ? {
                ...item,
                summary: data.summary,
                summaryUpdatedAt: Date.now(),
                summarizedMessageCount: compressUntil,
                updatedAt: Date.now(),
              }
            : item,
        ),
      );
    } catch (error) {
      if (mode === "manual") {
        const message = error instanceof Error ? error.message : "摘要生成失败";
        setActiveMessages((current) => [
          ...current,
          {
            id: makeId("assistant"),
            role: "assistant",
            content: `上下文压缩失败：${message}`,
            status: "error",
          },
        ]);
      }
    } finally {
      setSummarizing(false);
    }
  }

  async function maybeAutoSummarize(sessionId: string, messagesOverride?: DisplayMessage[]) {
    const session = sessionsRef.current.find((item) => item.id === sessionId);
    if (!session) {
      return;
    }

    try {
      const estimate = await estimateSessionContext(session, messagesOverride || session.messages);
      const usage = contextUsage(session, estimate);
      if (usage.ratio >= usage.threshold) {
        void summarizeSession(sessionId, "auto", messagesOverride);
      }
    } catch {
      // Context estimation is advisory; chat should continue even if this fails.
    }
  }

  async function sendMessage(text: string) {
    const content = text.trim();
    if (!content || pending) {
      return;
    }
    if (!activeSession) {
      return;
    }

    const nextUserMessage: DisplayMessage = {
      id: makeId("user"),
      role: "user",
      content,
    };

    const assistantId = makeId("assistant");
    const assistantMessage: DisplayMessage = {
      id: assistantId,
      role: "assistant",
      content: "",
      model: selectedModelId,
      steps: [],
      status: "streaming",
    };

    const nextMessages = [...messages, nextUserMessage];
    const renamedTitle = activeSession.title === "新会话" ? titleFromMessage(content) : activeSession.title;
    updateActiveSession((session) => ({
      ...session,
      title: renamedTitle,
      modelId: selectedModelId,
      messages: [...nextMessages, assistantMessage].slice(-MAX_STORED_MESSAGES),
    }));
    setInput("");
    setPending(true);

    const controller = new AbortController();
    abortRef.current = controller;
    const timeout = window.setTimeout(() => controller.abort(), 120000);

    try {
      const response = await fetch("/api/chat/stream", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          model: selectedModelId,
          session_id: activeSession.id,
          messages: buildContextMessages(activeSession, nextMessages),
        }),
        signal: controller.signal,
      });

      if (!response.body) {
        throw new Error("浏览器不支持流式响应");
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let sawDone = false;
      let streamedContent = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) {
          break;
        }

        buffer += decoder.decode(value, { stream: true });
        const parsed = parseSseFrames(buffer);
        buffer = parsed.rest;

        for (const item of parsed.events) {
          if (item.event === "error") {
            throw new Error(typeof item.data.message === "string" ? item.data.message : "请求失败");
          }

          if (item.event === "message_start") {
            setActiveMessages((current) =>
              current.map((message) =>
                message.id === assistantId && typeof item.data.model === "string"
                  ? { ...message, model: item.data.model }
                  : message,
              ),
            );
          }

          if (item.event === "tool_start" || item.event === "tool_result" || item.event === "tool_error") {
            const step = {
              ...item.data,
              id: typeof item.data.id === "string" ? item.data.id : item.data.step_id,
            } as ToolStep;

            setActiveMessages((current) =>
              current.map((message) =>
                message.id === assistantId
                  ? { ...message, steps: upsertStep(message.steps || [], step) }
                  : message,
              ),
            );
          }

          if (item.event === "text_delta" && typeof item.data.delta === "string") {
            streamedContent += item.data.delta;
            setActiveMessages((current) =>
              current.map((message) =>
                message.id === assistantId
                  ? { ...message, content: message.content + item.data.delta }
                  : message,
              ),
            );
          }

          if (item.event === "message_done") {
            sawDone = true;
            const finalAnswer = typeof item.data.answer === "string" ? item.data.answer : streamedContent;
            setActiveMessages((current) =>
              current.map((message) =>
                message.id === assistantId
                  ? {
                      ...message,
                      content: finalAnswer || message.content,
                      model: typeof item.data.model === "string" ? item.data.model : message.model,
                      steps: Array.isArray(item.data.steps) ? (item.data.steps as ToolStep[]) : message.steps,
                      status: "done",
                    }
                  : message,
              ),
            );
            window.setTimeout(
              () =>
                void maybeAutoSummarize(activeSession.id, [
                  ...nextMessages,
                  {
                    ...assistantMessage,
                    content: finalAnswer,
                    model: typeof item.data.model === "string" ? item.data.model : assistantMessage.model,
                    steps: Array.isArray(item.data.steps) ? (item.data.steps as ToolStep[]) : assistantMessage.steps,
                    status: "done",
                  },
                ]),
              0,
            );
          }
        }
      }

      if (!sawDone) {
        setActiveMessages((current) =>
          current.map((message) =>
            message.id === assistantId ? { ...message, status: "done" } : message,
          ),
        );
      }
    } catch (error) {
      const aborted = error instanceof Error && error.name === "AbortError";
      const message = error instanceof Error ? error.message : "请求失败";

      setActiveMessages((current) =>
        current.map((item) =>
          item.id === assistantId
            ? {
                ...item,
                status: aborted ? "stopped" : "error",
                content: item.content || (aborted ? "已停止生成。" : `出错了：${message}`),
              }
            : item,
        ),
      );
    } finally {
      window.clearTimeout(timeout);
      abortRef.current = null;
      setPending(false);
    }
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    sendMessage(input);
  }

  return (
    <div className="flex min-h-dvh bg-stone-100 text-stone-950">
      <aside className="hidden w-72 shrink-0 border-r border-stone-200 bg-stone-50/70 md:flex md:flex-col">
        <div className="flex h-14 items-center justify-between border-b border-stone-200 px-4">
          <span className="text-sm font-bold text-stone-900">会话</span>
          <button
            type="button"
            onClick={createSession}
            disabled={pending}
            aria-label="新建会话"
            className="grid h-8 w-8 place-items-center rounded-lg text-stone-500 transition hover:bg-stone-200 hover:text-stone-950 disabled:cursor-not-allowed disabled:opacity-40"
          >
            <Plus className="h-4 w-4" />
          </button>
        </div>
        <div className="border-b border-stone-200 p-3">
          <div className="flex items-center justify-between text-xs font-semibold text-stone-500">
            <span>上下文</span>
            <span>
              {activeContextUsage.loading
                ? "估算中"
                : activeContextUsage.error
                  ? "估算失败"
                : `${formatTokens(activeContextUsage.usedTokens)} / ${formatTokens(
                    activeContextUsage.limitTokens,
                  )} tokens · ${Math.round(activeContextUsage.ratio * 100)}%`}
            </span>
          </div>
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-stone-200">
            <div
              className={cn(
                "h-full rounded-full transition-all",
                activeContextUsage.ratio >= activeContextUsage.threshold ? "bg-amber-500" : "bg-emerald-500",
              )}
              style={{ width: `${Math.round(activeContextUsage.ratio * 100)}%` }}
            />
          </div>
          <div className="mt-2 flex items-center gap-2">
            <div className="grid min-w-0 flex-1 grid-cols-3 rounded-md border border-stone-200 bg-white p-0.5">
              {summaryThresholdOptions.map((option) => {
                const selected = (activeSession?.summaryTriggerRatio || SUMMARY_TRIGGER_RATIO) === option.value;
                return (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => updateSummaryTriggerRatio(option.value)}
                    disabled={pending || summarizing || !activeSession}
                    aria-pressed={selected}
                    className={cn(
                      "h-6 rounded px-1 text-xs font-semibold transition disabled:cursor-not-allowed disabled:opacity-40",
                      selected ? "bg-stone-900 text-white" : "text-stone-500 hover:bg-stone-100 hover:text-stone-900",
                    )}
                  >
                    {option.label}
                  </button>
                );
              })}
            </div>
            <button
              type="button"
              onClick={() => activeSession && summarizeSession(activeSession.id, "manual")}
              disabled={
                pending ||
                summarizing ||
                !activeSession ||
                eligibleContextMessages(activeSession.messages).length <= SUMMARY_KEEP_RECENT_MESSAGES
              }
              className="inline-flex h-7 items-center gap-1.5 rounded-md border border-stone-200 bg-white px-2 text-xs font-semibold text-stone-600 transition hover:border-amber-300 hover:text-stone-950 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {summarizing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Archive className="h-3.5 w-3.5" />}
              压缩
          </button>
        </div>
        <div className="mt-1 text-[11px] leading-4 text-stone-400">
          {activeContextUsage.error
            ? activeContextUsage.error
            : `预留输出 ${formatTokens(activeContextUsage.reservedOutputTokens)} tokens`}
        </div>
          {activeSession?.summary ? (
            <div className="mt-2 max-h-16 overflow-hidden rounded-md bg-white px-2 py-1.5 text-xs leading-5 text-stone-500">
              {activeSession.summary}
            </div>
          ) : null}
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-2">
          {sessions.map((session) => {
            const active = session.id === activeSessionId;
            return (
              <div
                key={session.id}
                className={cn(
                  "group grid grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-1 rounded-lg px-2 py-2 transition",
                  active ? "bg-white shadow-sm ring-1 ring-stone-200" : "hover:bg-stone-100",
                )}
              >
                {editingSessionId === session.id ? (
                  <input
                    value={editingTitle}
                    onChange={(event) => setEditingTitle(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") {
                        finishRenameSession();
                      }
                      if (event.key === "Escape") {
                        setEditingSessionId("");
                        setEditingTitle("");
                      }
                    }}
                    className="min-w-0 rounded-md border border-stone-200 bg-white px-2 py-1 text-sm outline-none focus:border-amber-400"
                    autoFocus
                  />
                ) : (
                  <button
                    type="button"
                    onClick={() => switchSession(session.id)}
                    disabled={pending}
                    className="min-w-0 text-left disabled:cursor-not-allowed"
                  >
                    <span className="flex min-w-0 items-center gap-2">
                      <MessageSquare className="h-3.5 w-3.5 shrink-0 text-stone-400" />
                      <span className="truncate text-sm font-semibold text-stone-800">
                        {session.title}
                      </span>
                    </span>
                    <span className="mt-0.5 block truncate pl-5 text-xs text-stone-400">
                      {session.messages.length} 条消息
                    </span>
                  </button>
                )}
                {editingSessionId === session.id ? (
                  <>
                    <button
                      type="button"
                      onClick={finishRenameSession}
                      aria-label="确认重命名"
                      className="grid h-7 w-7 place-items-center rounded-md text-stone-500 hover:bg-stone-200 hover:text-stone-950"
                    >
                      <Check className="h-3.5 w-3.5" />
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setEditingSessionId("");
                        setEditingTitle("");
                      }}
                      aria-label="取消重命名"
                      className="grid h-7 w-7 place-items-center rounded-md text-stone-500 hover:bg-stone-200 hover:text-stone-950"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </>
                ) : (
                  <>
                    <button
                      type="button"
                      onClick={() => startRenameSession(session)}
                      disabled={pending}
                      aria-label="重命名会话"
                      className="grid h-7 w-7 place-items-center rounded-md text-stone-400 opacity-0 transition hover:bg-stone-200 hover:text-stone-950 group-hover:opacity-100 disabled:cursor-not-allowed"
                    >
                      <Pencil className="h-3.5 w-3.5" />
                    </button>
                    <button
                      type="button"
                      onClick={() => deleteSession(session.id)}
                      disabled={pending}
                      aria-label="删除会话"
                      className="grid h-7 w-7 place-items-center rounded-md text-stone-400 opacity-0 transition hover:bg-rose-50 hover:text-rose-600 group-hover:opacity-100 disabled:cursor-not-allowed"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </>
                )}
              </div>
            );
          })}
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
      <header className="sticky top-0 z-20 flex h-14 items-center justify-between border-b border-stone-200 bg-stone-100/85 px-4 backdrop-blur-xl md:px-6">
        <div className="flex items-center gap-2.5">
          <div className="grid h-7 w-7 place-items-center rounded-lg text-amber-600">
            <Layers3 className="h-5 w-5" />
          </div>
          <span className="font-bold tracking-tight">手搓 Agent</span>
        </div>
        <button
          type="button"
          onClick={createSession}
          disabled={pending}
          className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-stone-200 px-2.5 text-xs font-semibold text-stone-500 md:hidden"
        >
          <Plus className="h-3.5 w-3.5" />
          新会话
        </button>
        <div className="hidden max-w-[56vw] items-center gap-2 overflow-hidden md:flex">
          {(tools.length ? tools : []).slice(0, 5).map((tool) => (
            <span
              key={tool.name}
              title={`${tool.description} · ${tool.permission}`}
              className="inline-flex min-w-0 items-center gap-1.5 rounded-full border border-stone-200 px-3 py-1 text-xs font-medium text-stone-500"
            >
              <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-500" />
              <span className="truncate">{tool.name}</span>
            </span>
          ))}
        </div>
      </header>

      <div className="border-b border-stone-200 bg-stone-100 px-3 py-2 md:hidden">
        <div className="flex gap-2 overflow-x-auto">
          {sessions.map((session) => (
            <button
              key={session.id}
              type="button"
              onClick={() => switchSession(session.id)}
              disabled={pending}
              className={cn(
                "shrink-0 rounded-full border px-3 py-1.5 text-xs font-semibold",
                session.id === activeSessionId
                  ? "border-stone-300 bg-white text-stone-950"
                  : "border-stone-200 text-stone-500",
              )}
            >
              {session.title}
            </button>
          ))}
        </div>
        <div className="mt-2 flex items-center gap-2 text-xs font-semibold text-stone-500">
          <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-stone-200">
            <div
              className={cn(
                "h-full rounded-full",
                activeContextUsage.ratio >= activeContextUsage.threshold ? "bg-amber-500" : "bg-emerald-500",
              )}
              style={{ width: `${Math.round(activeContextUsage.ratio * 100)}%` }}
            />
          </div>
          <span>
            {activeContextUsage.loading
              ? "估算中"
              : activeContextUsage.error
                ? "估算失败"
              : `${formatTokens(activeContextUsage.usedTokens)} / ${formatTokens(activeContextUsage.limitTokens)}`}
          </span>
          <button
            type="button"
            onClick={() => activeSession && summarizeSession(activeSession.id, "manual")}
            disabled={
              pending ||
              summarizing ||
              !activeSession ||
              eligibleContextMessages(activeSession.messages).length <= SUMMARY_KEEP_RECENT_MESSAGES
            }
            className="rounded-md border border-stone-200 bg-white px-2 py-1 text-xs font-semibold text-stone-600 disabled:opacity-40"
          >
            {summarizing ? "压缩中" : "压缩"}
          </button>
        </div>
      </div>

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
                        {message.status === "streaming" && !message.content ? (
                          <div className="flex items-center gap-2 py-1 text-sm text-stone-500">
                            <Loader2 className="h-4 w-4 animate-spin" />
                            Agent 思考中...
                          </div>
                        ) : null}
                        {message.status === "stopped" ? (
                          <div className="mt-2 text-xs font-semibold text-amber-600">已停止生成</div>
                        ) : null}
                        {message.model ? (
                          <div className="mt-2 text-xs font-medium text-stone-400">
                            使用模型：{models.find((model) => model.id === message.model)?.label || message.model}
                          </div>
                        ) : null}
                        <ToolSteps steps={message.steps || []} />
                      </div>
                    </>
                  )}
                </article>
              ))}

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
              type={pending ? "button" : "submit"}
              disabled={pending ? false : !input.trim() || !selectedModelId}
              aria-label={pending ? "停止生成" : "发送"}
              onClick={pending ? stopGeneration : undefined}
              className={cn(
                "absolute bottom-2.5 right-2.5 grid h-9 w-9 place-items-center rounded-xl text-white transition hover:scale-105 disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:scale-100",
                pending ? "bg-rose-600 hover:bg-rose-500" : "bg-stone-950 hover:bg-stone-800",
              )}
            >
              {pending ? <Square className="h-4 w-4 fill-current" /> : <ArrowUp className="h-4 w-4" />}
            </button>
          </form>
        </div>
        <p className="mt-2 text-center text-xs text-stone-400">Agent 可能会犯错，请核实重要信息。</p>
      </div>
      </div>
    </div>
  );
}
