"use client";

import {
  ArrowUp,
  Calculator,
  Clock3,
  Layers3,
  Loader2,
  MessageSquare,
  Pencil,
  Plus,
  Archive,
  Square,
  Trash2,
  Terminal,
  Settings,
  Sparkles,
  PanelLeftClose,
  PanelLeftOpen,
  Copy,
  Check,
  RotateCcw,
  Paperclip,
  Settings2,
} from "lucide-react";
import { FormEvent, useCallback, useEffect, useRef, useState } from "react";

import { MarkdownMessage } from "@/components/markdown-message";
import { ModelPicker } from "@/components/model-picker";
import { RuntimePicker } from "@/components/runtime-picker";
import { RuntimeArtifacts } from "@/components/runtime-artifacts";
import { RuntimeWorkbenchPanel } from "@/components/runtime-workbench-panel";
import { ToolSteps } from "@/components/tool-steps";
import { SkillManagerView } from "@/components/skill-manager-view";
import type { ModelOption, RuntimeArtifact, RuntimeEventPayload, RuntimeOption, RuntimeSessionRef, ToolOption, ToolStep } from "@/lib/types";
import { cn } from "@/lib/utils";

type DisplayMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  rawContent?: string; // 原始发送内容，用于重试
  turnId?: string;
  retryOfTurnId?: string;
  model?: string;
  runtime?: string;
  steps?: ToolStep[];
  artifacts?: RuntimeArtifact[];
  sessionRef?: RuntimeSessionRef | null;
  status?: "streaming" | "done" | "error" | "stopped" | "rolled_back" | "retrying";
};

type ChatSession = {
  id: string;
  title: string;
  createdAt: number;
  updatedAt: number;
  modelId: string;
  runtimeId: string;
  messages: DisplayMessage[];
  summary?: string;
  summaryUpdatedAt?: number;
  summarizedMessageCount?: number;
  summaryTriggerRatio?: number;
  trustedTools?: string[];
};

type StreamEvent = {
  event: string;
  data: RuntimeEventPayload;
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
const RUNTIME_STORAGE_KEY = "agent:runtime";
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

function makeSession(modelId = "", runtimeId = ""): ChatSession {
  const now = Date.now();
  return {
    id: makeId("session"),
    title: "新会话",
    createdAt: now,
    updatedAt: now,
    modelId,
    runtimeId,
    messages: [],
    summary: "",
    summaryUpdatedAt: undefined,
    summarizedMessageCount: 0,
    summaryTriggerRatio: SUMMARY_TRIGGER_RATIO,
    trustedTools: [],
  };
}

function titleFromMessage(content: string) {
  const title = content.trim().replace(/\s+/g, " ").slice(0, 28);
  return title || "新会话";
}

function parseSystemAction(content: string) {
  if (!content.startsWith('{"__system_action"')) {
    return null;
  }
  try {
    const action = JSON.parse(content) as Record<string, unknown>;
    return typeof action.__system_action === "string" ? action : null;
  } catch {
    return null;
  }
}

function displayTextForSystemAction(action: Record<string, unknown> | null) {
  if (!action) {
    return null;
  }
  if (action.__system_action === "answer_user_question") {
    const label = typeof action.label === "string" ? action.label : "";
    const answer = typeof action.answer === "string" ? action.answer : "";
    return label || answer || "已回答问题";
  }
  if (action.__system_action === "approve_tool") {
    return "批准并继续";
  }
  if (action.__system_action === "reject_tool") {
    return "拒绝执行";
  }
  return null;
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
    runtimeId: typeof session.runtimeId === "string" ? session.runtimeId : "",
    messages: Array.isArray(session.messages) ? session.messages.slice(-MAX_STORED_MESSAGES) : [],
    summary: typeof session.summary === "string" ? session.summary : "",
    summaryUpdatedAt: typeof session.summaryUpdatedAt === "number" ? session.summaryUpdatedAt : undefined,
    summarizedMessageCount:
      typeof session.summarizedMessageCount === "number" ? Math.max(0, session.summarizedMessageCount) : 0,
    summaryTriggerRatio:
      typeof session.summaryTriggerRatio === "number"
        ? Math.max(0.5, Math.min(1, session.summaryTriggerRatio))
        : SUMMARY_TRIGGER_RATIO,
    trustedTools: Array.isArray(session.trustedTools) ? session.trustedTools : [],
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

function readStoredActiveSessionRuntimeId() {
  const sessions = loadStoredSessions();
  const activeSessionId = window.localStorage.getItem(ACTIVE_SESSION_STORAGE_KEY);
  return sessions.find((session) => session.id === activeSessionId)?.runtimeId || "";
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

function contextUsage(
  session?: ChatSession,
  estimateState?: { estimate?: ContextEstimate; error?: string; messageCount?: number; contentLength?: number } | null,
) {
  const threshold = session?.summaryTriggerRatio || SUMMARY_TRIGGER_RATIO;
  const estimate = estimateState?.estimate;
  const estimateError = estimateState?.error || "";

  let extraTokens = 0;
  if (estimate && session?.messages) {
    const currentMessageCount = session.messages.length;
    const currentContentLength = session.messages.reduce((sum, m) => sum + (m.content?.length || 0), 0);
    
    if (currentMessageCount > (estimateState?.messageCount || 0) || currentContentLength > (estimateState?.contentLength || 0)) {
       const lengthDiff = Math.max(0, currentContentLength - (estimateState?.contentLength || 0));
       extraTokens = Math.ceil(lengthDiff * 0.8);
    }
  }

  if (estimate) {
    const usedTokens = estimate.input_tokens + extraTokens;
    const ratio = estimate.context_window_tokens > 0 ? usedTokens / estimate.context_window_tokens : 0;
    return {
      usedTokens,
      limitTokens: estimate.context_window_tokens,
      availableTokens: Math.max(0, estimate.context_window_tokens - usedTokens),
      reservedOutputTokens: estimate.reserved_output_tokens,
      ratio: Math.min(1, Math.max(0, ratio)),
      threshold,
      estimator: extraTokens > 0 ? "approximate" : estimate.estimator,
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
      return [{ event, data: JSON.parse(dataLines.join("\n")) as RuntimeEventPayload }];
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

function isRuntimeArtifact(value: unknown): value is RuntimeArtifact {
  return Boolean(
    value &&
      typeof value === "object" &&
      typeof (value as RuntimeArtifact).id === "string" &&
      typeof (value as RuntimeArtifact).type === "string",
  );
}

function isRuntimeSessionRef(value: unknown): value is RuntimeSessionRef {
  return Boolean(value && typeof value === "object");
}

function upsertArtifact(artifacts: RuntimeArtifact[], artifact: RuntimeArtifact) {
  const index = artifacts.findIndex((item) => item.id === artifact.id);
  if (index === -1) {
    return [...artifacts, artifact];
  }
  return artifacts.map((item, itemIndex) => (itemIndex === index ? { ...item, ...artifact } : item));
}

function latestAssistantIndex(messages: DisplayMessage[]) {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    if (messages[index].role === "assistant") {
      return index;
    }
  }
  return -1;
}

function modelSupportedByRuntime(runtime?: RuntimeOption, modelId?: string) {
  if (!runtime?.supported_model_ids?.length || !modelId) {
    return true;
  }
  return runtime.supported_model_ids.includes(modelId);
}

export function AgentChat() {
  const [models, setModels] = useState<ModelOption[]>([]);
  const [runtimes, setRuntimes] = useState<RuntimeOption[]>([]);
  const [, setTools] = useState<ToolOption[]>([]);
  const [selectedModelId, setSelectedModelId] = useState("");
  const [selectedRuntimeId, setSelectedRuntimeId] = useState("");
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState("");
  const [sessionsLoaded, setSessionsLoaded] = useState(false);
  const [editingSessionId, setEditingSessionId] = useState("");
  const [editingTitle, setEditingTitle] = useState("");
  const [input, setInput] = useState("");
  const [isComposing, setIsComposing] = useState(false);
  const [pending, setPending] = useState(false);
  const [summarizing, setSummarizing] = useState(false);
  const [artifactRefreshing, setArtifactRefreshing] = useState(false);
  const [contextEstimateState, setContextEstimateState] = useState<{
    sessionId: string;
    estimate?: ContextEstimate;
    error?: string;
    messageCount?: number;
    contentLength?: number;
  } | null>(null);
  const [view, setView] = useState<"chat" | "skills">("chat");
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [loadError, setLoadError] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [isMobileSidebarOpen, setIsMobileSidebarOpen] = useState(false);
  const [showContextDetails, setShowContextDetails] = useState(false);
  const autoScrollEnabled = useRef(true);
  const [isAtBottom, setIsAtBottom] = useState(true);
  const [hasUnread, setHasUnread] = useState(false);
  const [showScrollButton, setShowScrollButton] = useState(false);
  const [copiedMessageId, setCopiedMessageId] = useState<string | null>(null);
  const [editingMessageId, setEditingMessageId] = useState<string | null>(null);
  const [editingContent, setEditingContent] = useState("");
  const [retryConfirmMessageId, setRetryConfirmMessageId] = useState<string | null>(null);
  const [retryingTurnId, setRetryingTurnId] = useState<string | null>(null);
  const sessionsRef = useRef<ChatSession[]>([]);
  const activeSession = sessions.find((session) => session.id === activeSessionId);
  const messages = activeSession?.messages ?? EMPTY_MESSAGES;
  const latestAssistantMessage = [...messages].reverse().find((message) => message.role === "assistant");
  const activeRuntime = runtimes.find((runtime) => runtime.id === (latestAssistantMessage?.runtime || activeSession?.runtimeId || selectedRuntimeId));
  const activeModel = models.find((model) => model.id === (latestAssistantMessage?.model || activeSession?.modelId || selectedModelId));
  const activeContextEstimateState = contextEstimateState?.sessionId === activeSessionId ? contextEstimateState : null;
  const activeContextUsage = contextUsage(activeSession, activeContextEstimateState);

  const contextPercentageText =
    activeContextUsage.usedTokens > 0 && activeContextUsage.ratio * 100 < 1
      ? "<1"
      : Math.round(activeContextUsage.ratio * 100);
  const contextProgressWidth =
    activeContextUsage.usedTokens > 0 ? Math.max(1, activeContextUsage.ratio * 100) : 0;

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
    async function loadRuntimes() {
      try {
        const response = await fetch("/api/runtimes", { cache: "no-store" });
        const data = await readJsonResponse<{ runtimes?: RuntimeOption[]; default?: string; error?: string }>(
          response,
          "Agent Runtime 列表加载失败",
        );
        if (data.error) {
          throw new Error(data.error);
        }
        if (!response.ok || !Array.isArray(data.runtimes)) {
          throw new Error("Agent Runtime 列表加载失败");
        }

        const savedRuntimeId = readStoredActiveSessionRuntimeId() || window.localStorage.getItem(RUNTIME_STORAGE_KEY);
        const availableRuntimes = data.runtimes.filter((runtime) => runtime.available);
        const nextRuntimeId =
          availableRuntimes.find((runtime) => runtime.id === savedRuntimeId)?.id ||
          availableRuntimes.find((runtime) => runtime.id === data.default)?.id ||
          availableRuntimes[0]?.id ||
          data.default ||
          data.runtimes[0]?.id ||
          "";

        setRuntimes(data.runtimes);
        setSelectedRuntimeId(nextRuntimeId);
      } catch (error) {
        setLoadError(error instanceof Error ? error.message : "Agent Runtime 列表加载失败");
      }
    }

    loadRuntimes();
  }, []);

  useEffect(() => {
    async function loadSessions() {
      await Promise.resolve();
      const storedSessions = loadStoredSessions();
      const storedRuntimeId = window.localStorage.getItem(RUNTIME_STORAGE_KEY) || "";
      const nextSessions = storedSessions.length ? storedSessions : [makeSession("", storedRuntimeId)];
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
    const currentMessages = activeSession.messages;
    const messageCount = currentMessages.length;
    const contentLength = currentMessages.reduce((sum, m) => sum + (m.content?.length || 0), 0);

    estimateSessionContext(activeSession, currentMessages, controller.signal)
      .then((estimate) => setContextEstimateState({ sessionId: activeSession.id, estimate, messageCount, contentLength }))
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

  const scrollToBottom = () => {
    autoScrollEnabled.current = true;
    setIsAtBottom(true);
    setHasUnread(false);
    setShowScrollButton(false);
    scrollRef.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  };

  const handleScroll = () => {
    if (!containerRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = containerRef.current;
    
    // 100px threshold
    const atBottom = scrollHeight - scrollTop - clientHeight < 100;
    
    if (atBottom !== isAtBottom) {
      setIsAtBottom(atBottom);
      if (atBottom) {
        setHasUnread(false);
        autoScrollEnabled.current = true;
      } else {
        autoScrollEnabled.current = false;
      }
    }
    
    // Toggle scroll button visibility
    const show = scrollHeight - scrollTop - clientHeight > 300;
    if (show !== showScrollButton) {
      setShowScrollButton(show);
    }
  };

  // Auto scroll effect
  useEffect(() => {
    if (autoScrollEnabled.current) {
      scrollRef.current?.scrollIntoView({ block: "end", behavior: "smooth" });
    } else if (pending) {
      const frame = window.requestAnimationFrame(() => setHasUnread(true));
      return () => window.cancelAnimationFrame(frame);
    }
  }, [messages, pending]);

  function selectModel(modelId: string) {
    setSelectedModelId(modelId);
    window.localStorage.setItem("agent:model", modelId);
    if (activeSessionId) {
      updateActiveSession((session) => ({ ...session, modelId }));
    }
  }

  function selectRuntime(runtimeId: string) {
    const runtime = runtimes.find((item) => item.id === runtimeId);
    setSelectedRuntimeId(runtimeId);
    window.localStorage.setItem(RUNTIME_STORAGE_KEY, runtimeId);

    let nextModelId = selectedModelId;
    if (runtime && !modelSupportedByRuntime(runtime, selectedModelId)) {
      const fallbackModel = models.find((model) => model.available && modelSupportedByRuntime(runtime, model.id));
      if (fallbackModel) {
        nextModelId = fallbackModel.id;
        setSelectedModelId(fallbackModel.id);
        window.localStorage.setItem("agent:model", fallbackModel.id);
      }
    }

    if (activeSessionId) {
      updateActiveSession((session) => ({ ...session, runtimeId, modelId: nextModelId }));
    }
  }

  function createSession() {
    if (pending) {
      return;
    }

    const session = makeSession(selectedModelId, selectedRuntimeId);
    setSessions((current) => [session, ...current].slice(0, MAX_SESSIONS));
    setActiveSessionId(session.id);
    setInput("");
    setIsMobileSidebarOpen(false);
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
    if (session.runtimeId) {
      setSelectedRuntimeId(session.runtimeId);
    }
    setInput("");
    setIsMobileSidebarOpen(false);
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
        setSelectedRuntimeId(remaining[0].runtimeId || selectedRuntimeId);
      }
      return;
    }

    const fallback = makeSession(selectedModelId, selectedRuntimeId);
    setSessions([fallback]);
    setActiveSessionId(fallback.id);
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
    if (activeSession?.runtimeId && activeSession.id) {
      void fetch("/api/runtime/abort", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          runtime: activeSession.runtimeId,
          session_id: activeSession.id,
        }),
      }).catch(() => {
        // The local request abort already stops the UI; runtime abort is best-effort.
      });
    }
  }

  async function refreshRuntimeArtifacts(runtimeId?: string, sessionId?: string) {
    const targetRuntimeId = runtimeId || activeSession?.runtimeId || selectedRuntimeId;
    const targetSessionId = sessionId || activeSession?.id;
    if (!targetRuntimeId || !targetSessionId || artifactRefreshing) {
      return;
    }

    setArtifactRefreshing(true);
    try {
      const params = new URLSearchParams({
        runtime: targetRuntimeId,
        session_id: targetSessionId,
      });
      const response = await fetch(`/api/runtime/artifacts?${params.toString()}`, { cache: "no-store" });
      const data = await readJsonResponse<{
        artifacts?: RuntimeArtifact[];
        session_ref?: RuntimeSessionRef | null;
        error?: string;
      }>(response, "Runtime 产物刷新失败");
      if (!response.ok || data.error) {
        throw new Error(data.error || "Runtime 产物刷新失败");
      }

      const artifacts = Array.isArray(data.artifacts) ? data.artifacts.filter(isRuntimeArtifact) : [];
      setActiveMessages((current) => {
        const index = latestAssistantIndex(current);
        if (index === -1) {
          return current;
        }
        return current.map((message, itemIndex) =>
          itemIndex === index
            ? {
                ...message,
                artifacts,
                sessionRef: isRuntimeSessionRef(data.session_ref) ? data.session_ref : message.sessionRef,
              }
            : message,
        );
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : "Runtime 产物刷新失败";
      setActiveMessages((current) => {
        const index = latestAssistantIndex(current);
        if (index === -1) {
          return current;
        }
        const diagnostic: RuntimeArtifact = {
          id: `runtime-artifact-refresh-error-${Date.now()}`,
          type: "diagnostic",
          title: "Artifact Refresh Failed",
          status: "error",
          data: { message },
        };
        return current.map((item, itemIndex) =>
          itemIndex === index
            ? { ...item, artifacts: upsertArtifact(item.artifacts || [], diagnostic) }
            : item,
        );
      });
    } finally {
      setArtifactRefreshing(false);
    }
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
      const usage = contextUsage(session, { estimate });
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

    const selectedRuntime = runtimes.find((runtime) => runtime.id === selectedRuntimeId);
    let requestModelId = selectedModelId;
    if (selectedRuntime && !modelSupportedByRuntime(selectedRuntime, selectedModelId)) {
      const fallbackModel = models.find((model) => model.available && modelSupportedByRuntime(selectedRuntime, model.id));
      if (fallbackModel) {
        requestModelId = fallbackModel.id;
        setSelectedModelId(fallbackModel.id);
        window.localStorage.setItem("agent:model", fallbackModel.id);
      }
    }

    const systemAction = parseSystemAction(content);
    const displayContent = displayTextForSystemAction(systemAction) || content;

    let toolToTrust = "";
    if (
      systemAction?.__system_action === "approve_tool" &&
      systemAction.trust_session &&
      typeof systemAction.tool === "string"
    ) {
      toolToTrust = systemAction.tool;
    }

    const nextUserMessage: DisplayMessage = {
      id: makeId("user"),
      role: "user",
      content: displayContent,
      rawContent: content, // 保存原始内容用于重试
    };

    const assistantId = makeId("assistant");
    const assistantMessage: DisplayMessage = {
      id: assistantId,
      role: "assistant",
      content: "",
      model: requestModelId,
      runtime: selectedRuntimeId,
      steps: [],
      status: "streaming",
    };

    const nextMessages = [...messages, nextUserMessage];
    const requestMessages = [
      ...messages,
      {
        ...nextUserMessage,
        content,
      },
    ];
    const renamedTitle =
      activeSession.title === "新会话" && !systemAction ? titleFromMessage(displayContent) : activeSession.title;
    
    const nextTrustedTools = toolToTrust 
      ? Array.from(new Set([...(activeSession.trustedTools || []), toolToTrust]))
      : activeSession.trustedTools || [];

    updateActiveSession((session) => ({
      ...session,
      title: renamedTitle,
      modelId: requestModelId,
      runtimeId: selectedRuntimeId,
      messages: [...nextMessages, assistantMessage].slice(-MAX_STORED_MESSAGES),
      trustedTools: nextTrustedTools,
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
          model: requestModelId,
          runtime: selectedRuntimeId,
          session_id: activeSession.id,
          messages: buildContextMessages(activeSession, requestMessages),
          trusted_tools: nextTrustedTools,
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
                message.id === assistantId
                  ? {
                      ...message,
                      turnId: typeof item.data.turn_id === "string" ? item.data.turn_id : message.turnId,
                      model: typeof item.data.model === "string" ? item.data.model : message.model,
                      runtime: typeof item.data.runtime === "string" ? item.data.runtime : message.runtime,
                      sessionRef: isRuntimeSessionRef(item.data.session_ref) ? item.data.session_ref : message.sessionRef,
                    }
                  : message,
              ),
            );
          }

          if (
            item.event === "tool_start" ||
            item.event === "tool_result" ||
            item.event === "tool_error" ||
            item.event === "tool_awaiting_approval"
          ) {
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

          if (item.event === "artifact_created" || item.event === "artifact_updated") {
            const artifact = item.data.artifact;
            if (isRuntimeArtifact(artifact)) {
              setActiveMessages((current) =>
                current.map((message) =>
                  message.id === assistantId
                    ? { ...message, artifacts: upsertArtifact(message.artifacts || [], artifact) }
                    : message,
                ),
              );
            }
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
                      runtime: typeof item.data.runtime === "string" ? item.data.runtime : message.runtime,
                      steps: Array.isArray(item.data.steps) ? (item.data.steps as ToolStep[]) : message.steps,
                      artifacts: Array.isArray(item.data.artifacts)
                        ? item.data.artifacts.filter(isRuntimeArtifact)
                        : message.artifacts,
                      sessionRef: isRuntimeSessionRef(item.data.session_ref) ? item.data.session_ref : message.sessionRef,
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
                    runtime: typeof item.data.runtime === "string" ? item.data.runtime : assistantMessage.runtime,
                    steps: Array.isArray(item.data.steps) ? (item.data.steps as ToolStep[]) : assistantMessage.steps,
                    artifacts: Array.isArray(item.data.artifacts) ? item.data.artifacts.filter(isRuntimeArtifact) : [],
                    sessionRef: isRuntimeSessionRef(item.data.session_ref) ? item.data.session_ref : null,
                    status: "done",
                  },
                ]),
              0,
            );
            window.setTimeout(() => {
              void refreshRuntimeArtifacts(selectedRuntimeId, activeSession.id);
            }, 250);
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

  async function retryTurn(message: DisplayMessage) {
    if (!message.turnId || !activeSession || pending || retryingTurnId) {
      return;
    }

    setRetryConfirmMessageId(null);
    setRetryingTurnId(message.turnId);
    setPending(true);

    setActiveMessages((current) =>
      current.map((item) =>
        item.id === message.id ? { ...item, status: "retrying" } : item,
      ),
    );

    try {
      const response = await fetch("/api/turns/retry", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ turn_id: message.turnId }),
      });
      const data = await readJsonResponse<{
        ok?: boolean;
        error?: string;
        new_turn_id?: string;
        answer?: string;
        steps?: ToolStep[];
        trace_id?: string;
        model?: string;
        runtime?: string;
      }>(response, "回滚重试失败");

      if (!response.ok || data.ok === false) {
        throw new Error(data.error || "回滚重试失败");
      }

      const newAssistantMessage: DisplayMessage = {
        id: makeId("assistant"),
        role: "assistant",
        content: data.answer || "",
        turnId: data.new_turn_id,
        retryOfTurnId: message.turnId,
        model: data.model,
        runtime: data.runtime,
        steps: Array.isArray(data.steps) ? data.steps : [],
        status: "done",
      };

      setActiveMessages((current) => {
        const next = current.map((item) =>
          item.id === message.id ? { ...item, status: "rolled_back" as const } : item,
        );
        const index = next.findIndex((item) => item.id === message.id);
        if (index === -1) {
          return [...next, newAssistantMessage];
        }
        return [...next.slice(0, index + 1), newAssistantMessage, ...next.slice(index + 1)];
      });
    } catch (error) {
      const messageText = error instanceof Error ? error.message : "回滚重试失败";
      setActiveMessages((current) =>
        current.map((item) =>
          item.id === message.id ? { ...item, status: "done", content: item.content || `出错了：${messageText}` } : item,
        ),
      );
      setLoadError(messageText);
    } finally {
      setRetryingTurnId(null);
      setPending(false);
    }
  }

  async function editAndRetryMessage(messageId: string, newContent: string) {
    console.log("[editAndRetry] called", { messageId, newContent, pending, activeSessionId: activeSession?.id });
    if (!activeSession || pending) {
      console.log("[editAndRetry] early return: no session or pending");
      return;
    }

    const messageIndex = messages.findIndex((m) => m.id === messageId);
    if (messageIndex < 0 || messages[messageIndex].role !== "user") {
      return;
    }

    const content = newContent.trim();
    if (!content) {
      return;
    }

    // Find the assistant message that follows this user message to get its turnId
    const assistantMessage = messages.find(
      (m, i) => i > messageIndex && m.role === "assistant" && m.turnId,
    );
    console.log("[editAndRetry] assistantMessage found?", assistantMessage?.id, "turnId?", assistantMessage?.turnId);

    if (assistantMessage?.turnId) {
      // Use rollback-and-retry API with edited content
      setRetryConfirmMessageId(null);
      setRetryingTurnId(assistantMessage.turnId);
      setPending(true);

      setActiveMessages((current) =>
        current.map((item) =>
          item.id === assistantMessage.id ? { ...item, status: "retrying" } : item,
        ),
      );

      try {
        const response = await fetch("/api/turns/retry", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ turn_id: assistantMessage.turnId, edited_content: content }),
        });
        const data = await readJsonResponse<{
          ok?: boolean;
          error?: string;
          new_turn_id?: string;
          answer?: string;
          steps?: ToolStep[];
          trace_id?: string;
          model?: string;
          runtime?: string;
        }>(response, "回滚重试失败");

        if (!response.ok || data.ok === false) {
          throw new Error(data.error || "回滚重试失败");
        }

        const newAssistantMessage: DisplayMessage = {
          id: makeId("assistant"),
          role: "assistant",
          content: data.answer || "",
          turnId: data.new_turn_id,
          retryOfTurnId: assistantMessage.turnId,
          model: data.model,
          runtime: data.runtime,
          steps: Array.isArray(data.steps) ? data.steps : [],
          status: "done",
        };

        // Update the user message content as well
        setActiveMessages((current) => {
          const next = current.map((item) =>
            item.id === messageId
              ? { ...item, content, rawContent: content }
              : item.id === assistantMessage.id
                ? { ...item, status: "rolled_back" as const }
                : item,
          );
          const idx = next.findIndex((item) => item.id === assistantMessage.id);
          if (idx === -1) {
            return [...next, newAssistantMessage];
          }
          return [...next.slice(0, idx + 1), newAssistantMessage, ...next.slice(idx + 1)];
        });
      } catch (error) {
        const messageText = error instanceof Error ? error.message : "回滚重试失败";
        setActiveMessages((current) =>
          current.map((item) =>
            item.id === assistantMessage.id
              ? { ...item, status: "done", content: item.content || `出错了：${messageText}` }
              : item,
          ),
        );
        setLoadError(messageText);
      } finally {
        setRetryingTurnId(null);
        setPending(false);
      }
      return;
    }

    // Fallback: no turnId available, use old frontend-only retry
    console.log("[editAndRetry] using fallback path (no turnId)");
    const selectedRuntime = runtimes.find((runtime) => runtime.id === selectedRuntimeId);
    let requestModelId = selectedModelId;
    if (selectedRuntime && !modelSupportedByRuntime(selectedRuntime, selectedModelId)) {
      const fallbackModel = models.find((model) => model.available && modelSupportedByRuntime(selectedRuntime, model.id));
      if (fallbackModel) {
        requestModelId = fallbackModel.id;
        setSelectedModelId(fallbackModel.id);
        window.localStorage.setItem("agent:model", fallbackModel.id);
      }
    }

    const messagesBeforeEdit = messages.slice(0, messageIndex);
    const newUserMessage: DisplayMessage = { id: makeId("user"), role: "user", content, rawContent: content };
    const assistantId = makeId("assistant");
    const assistantMessagePlaceholder: DisplayMessage = {
      id: assistantId,
      role: "assistant",
      content: "",
      model: requestModelId,
      runtime: selectedRuntimeId,
      steps: [],
      status: "streaming",
    };
    const updatedMessages = [...messagesBeforeEdit, newUserMessage, assistantMessagePlaceholder];
    updateActiveSession((session) => ({
      ...session,
      messages: updatedMessages.slice(-MAX_STORED_MESSAGES),
      modelId: requestModelId,
      runtimeId: selectedRuntimeId,
    }));
    setPending(true);
    const controller = new AbortController();
    abortRef.current = controller;
    const timeout = window.setTimeout(() => controller.abort(), 120000);

    try {
      const response = await fetch("/api/chat/stream", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          model: requestModelId,
          runtime: selectedRuntimeId,
          session_id: activeSession.id,
          messages: buildContextMessages(activeSession, [...messagesBeforeEdit, { ...newUserMessage, content }]),
          trusted_tools: activeSession.trustedTools || [],
        }),
        signal: controller.signal,
      });
      if (!response.body) throw new Error("浏览器不支持流式响应");
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let sawDone = false;
      let streamedContent = "";
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parsed = parseSseFrames(buffer);
        buffer = parsed.rest;
        for (const item of parsed.events) {
          if (item.event === "error") throw new Error(typeof item.data.message === "string" ? item.data.message : "请求失败");
          if (item.event === "text_delta" && typeof item.data.delta === "string") {
            streamedContent += item.data.delta;
            setActiveMessages((current) => current.map((msg) => msg.id === assistantId ? { ...msg, content: msg.content + item.data.delta } : msg));
          }
          if (item.event === "message_done") {
            sawDone = true;
            const finalAnswer = typeof item.data.answer === "string" ? item.data.answer : streamedContent;
            setActiveMessages((current) =>
              current.map((msg) =>
                msg.id === assistantId
                  ? { ...msg, content: finalAnswer || msg.content, model: typeof item.data.model === "string" ? item.data.model : msg.model, runtime: typeof item.data.runtime === "string" ? item.data.runtime : msg.runtime, steps: Array.isArray(item.data.steps) ? item.data.steps as ToolStep[] : msg.steps, status: "done", turnId: typeof item.data.turn_id === "string" ? item.data.turn_id : msg.turnId }
                  : msg,
              ),
            );
          }
        }
        if (sawDone) break;
      }
    } catch (error) {
      const aborted = error instanceof Error && error.name === "AbortError";
      const messageText = error instanceof Error ? error.message : "请求失败";
      setActiveMessages((current) =>
        current.map((item) =>
          item.id === assistantId ? { ...item, status: aborted ? "stopped" : "error", content: item.content || (aborted ? "已停止生成。" : `出错了：${messageText}`) } : item,
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
    autoScrollEnabled.current = true;
    setIsAtBottom(true);
    sendMessage(input);
    window.setTimeout(scrollToBottom, 50);
  }

  return (
    <div className="flex h-dvh w-full overflow-hidden bg-canvas text-ink selection:bg-primary-coral/10">
      {/* 1. 图标导航栏 (左侧最窄) */}
      <nav className="hidden w-[68px] shrink-0 flex-col items-center border-r border-hairline bg-canvas/50 py-5 text-muted-soft md:flex">
        <div className="mb-8 grid h-10 w-10 place-items-center rounded-xl bg-primary-coral text-white shadow-lg shadow-primary-coral/20">
          <Sparkles className="h-5 w-5" />
        </div>
        
        <div className="flex flex-1 flex-col gap-5">
          <button
            onClick={() => setView("chat")}
            className={cn(
              "group relative grid h-11 w-11 cursor-pointer place-items-center rounded-xl transition-all active:scale-95",
              view === "chat" ? "bg-primary-coral/5 text-primary-coral" : "text-muted hover:bg-stone-100 hover:text-ink"
            )}
            title="聊天"
          >
            <MessageSquare className="h-5 w-5" />
            {view === "chat" && <div className="absolute left-0 h-4 w-0.5 rounded-r-full bg-primary-coral" />}
          </button>
          
          <button
            onClick={() => setView("skills")}
            className={cn(
              "group relative grid h-11 w-11 cursor-pointer place-items-center rounded-xl transition-all active:scale-95",
              view === "skills" ? "bg-primary-coral/5 text-primary-coral" : "text-muted hover:bg-stone-100 hover:text-ink"
            )}
            title="技能与工具"
          >
            <Terminal className="h-5 w-5" />
            {view === "skills" && <div className="absolute left-0 h-4 w-0.5 rounded-r-full bg-primary-coral" />}
          </button>
        </div>

        <div className="mt-auto flex flex-col gap-5">
          <button className="grid h-10 w-10 place-items-center rounded-xl text-muted transition hover:bg-stone-100 hover:text-ink active:scale-95">
            <Settings className="h-5 w-5" />
          </button>
        </div>
      </nav>

      {view === "chat" ? (
        <>
          {/* 移动端侧边栏遮罩 */}
          {isMobileSidebarOpen && (
            <div 
              className="fixed inset-0 z-40 bg-ink/10 backdrop-blur-[2px] transition-opacity md:hidden"
              onClick={() => setIsMobileSidebarOpen(false)}
            />
          )}

          {/* 2. 会话列表侧边栏 */}
          <aside className={cn(
            "fixed inset-y-0 left-0 z-50 flex w-[280px] shrink-0 flex-col border-r border-hairline bg-canvas transition-all duration-300 ease-in-out md:relative md:z-auto md:bg-canvas/30",
            isSidebarCollapsed ? "md:w-0 md:opacity-0 md:overflow-hidden md:border-r-0" : "md:w-[280px] md:opacity-100",
            isMobileSidebarOpen ? "translate-x-0" : "-translate-x-full md:translate-x-0"
          )}>
            {/* Mobile Backdrop */}
            {isMobileSidebarOpen && (
              <div 
                className="fixed inset-0 z-40 bg-ink/10 backdrop-blur-[1px] md:hidden" 
                onClick={() => setIsMobileSidebarOpen(false)}
              />
            )}

            <div className="flex h-14 items-center justify-between px-4 shrink-0">
              <span className="text-[11px] font-bold text-muted-soft uppercase tracking-widest">Chat History</span>
              <div className="flex items-center gap-0.5">
                <button
                  type="button"
                  onClick={createSession}
                  disabled={pending}
                  title="新建会话"
                  className="grid h-8 w-8 cursor-pointer place-items-center rounded-lg text-muted transition hover:bg-stone-100 hover:text-ink active:scale-95 disabled:cursor-not-allowed disabled:opacity-30"
                >
                  <Plus className="h-4 w-4" />
                </button>
                <button
                  type="button"
                  onClick={() => setIsSidebarCollapsed(true)}
                  title="收起侧边栏"
                  className="hidden h-8 w-8 cursor-pointer place-items-center rounded-lg text-muted transition hover:bg-stone-100 hover:text-ink active:scale-95 md:grid"
                >
                  <PanelLeftClose className="h-4 w-4" />
                </button>
              </div>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto px-2 py-2 scrollbar-none">
              <div className="space-y-0.5">
                {sessions.map((session) => {
                  const active = session.id === activeSessionId;
                  return (
                    <div
                      key={session.id}
                      className={cn(
                        "group relative flex items-center rounded-xl transition-all active:scale-[0.98]",
                        active ? "bg-white text-primary-coral shadow-[0_2px_8px_rgba(0,0,0,0.04)] ring-1 ring-black/[0.03]" : "text-body hover:bg-stone-200/40"
                      )}
                    >
                      <button
                        type="button"
                        onClick={() => switchSession(session.id)}
                        disabled={pending}
                        className="flex min-w-0 flex-1 cursor-pointer items-center gap-3 px-3 py-2.5 text-left disabled:cursor-not-allowed"
                      >
                        <MessageSquare className={cn("h-4 w-4 shrink-0 transition-colors", active ? "text-primary-coral" : "text-muted-soft")} />
                        <div className="min-w-0 flex-1">
                          {editingSessionId === session.id ? (
                            <input
                              autoFocus
                              type="text"
                              value={editingTitle}
                              onChange={(e) => setEditingTitle(e.target.value)}
                              onBlur={finishRenameSession}
                              onKeyDown={(e) => {
                                if (e.key === "Enter") finishRenameSession();
                                if (e.key === "Escape") setEditingSessionId("");
                              }}
                              className="w-full bg-white px-1 text-[13.5px] font-semibold leading-tight outline-none ring-2 ring-primary-coral/20 rounded"
                              onClick={(e) => e.stopPropagation()}
                            />
                          ) : (
                            <div className={cn("truncate text-[13.5px] font-semibold leading-tight tracking-tight", active ? "text-ink" : "text-body")}>
                              {session.title}
                            </div>
                          )}
                          <div className="mt-0.5 flex items-center gap-2">
                            <span className="truncate text-[10px] text-muted-soft font-medium">
                              {session.messages.length} messages
                            </span>
                          </div>
                        </div>
                      </button>
                      
                      <div className="absolute right-2 flex items-center gap-0.5 opacity-0 transition group-hover:opacity-100">
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            startRenameSession(session);
                          }}
                          disabled={pending}
                          className="grid h-7 w-7 place-items-center rounded-lg text-muted-soft hover:bg-stone-100 hover:text-ink"
                          title="重命名"
                        >
                          <Pencil className="h-3.5 w-3.5" />
                        </button>
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            deleteSession(session.id);
                          }}
                          disabled={pending}
                          className="grid h-7 w-7 place-items-center rounded-lg text-muted-soft hover:bg-rose-50 hover:text-rose-600"
                          title="删除会话"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* 3. 上下文状态区域 (折叠式) */}
            <div className="border-t border-hairline p-2">
              <button
                type="button"
                onClick={() => setShowContextDetails(!showContextDetails)}
                className="flex w-full items-center justify-between rounded-lg px-3 py-2 text-[10px] font-bold text-muted-soft uppercase tracking-widest transition hover:bg-stone-100"
              >
                <span className="flex items-center gap-1.5">
                  <div className={cn(
                    "h-1.5 w-1.5 rounded-full",
                    activeContextUsage.ratio >= activeContextUsage.threshold ? "bg-amber-500" : "bg-emerald-500"
                  )} />
                  Context Usage
                </span>
                <span className={cn(
                  "tabular-nums",
                  activeContextUsage.ratio >= activeContextUsage.threshold ? "text-amber-600" : "text-emerald-600"
                )}>
                  {contextPercentageText}%
                </span>
              </button>
              
              {showContextDetails && (
                <div className="mt-2 space-y-2 rounded-xl bg-stone-50/50 p-3 ring-1 ring-black/[0.03]">
                  <div className="flex items-center justify-between text-[10px] font-medium text-muted">
                    <span>Tokens</span>
                    <span>{formatTokens(activeContextUsage.usedTokens)} / {formatTokens(activeContextUsage.limitTokens)}</span>
                  </div>
                  <div className="h-1 overflow-hidden rounded-full bg-stone-200">
                    <div
                      className={cn(
                        "h-full rounded-full transition-all duration-500",
                        activeContextUsage.ratio >= activeContextUsage.threshold ? "bg-amber-500" : "bg-emerald-500",
                      )}
                      style={{ width: `${contextProgressWidth}%` }}
                    />
                  </div>
                  <div className="flex items-center gap-2 pt-1">
                    <button
                      type="button"
                      onClick={() => activeSession && summarizeSession(activeSession.id, "manual")}
                      disabled={pending || summarizing || !activeSession || messages.length < 5}
                      className="flex h-7 flex-1 cursor-pointer items-center justify-center gap-1.5 rounded-lg border border-hairline bg-white text-[10px] font-bold text-ink shadow-sm transition hover:bg-stone-50 active:scale-95 disabled:cursor-not-allowed disabled:opacity-30"
                    >
                      {summarizing ? <Loader2 className="h-3 w-3 animate-spin" /> : <Archive className="h-3 w-3 text-muted" />}
                      Compress Context
                    </button>
                  </div>
                  <div className="text-center text-[9px] text-muted-soft">
                    Reserved: {formatTokens(activeContextUsage.reservedOutputTokens)} tokens
                  </div>
                </div>
              )}
            </div>
          </aside>

          <div className="relative flex min-w-0 flex-1 flex-col bg-canvas overflow-hidden">
            <header className="sticky top-0 z-20 flex h-14 shrink-0 items-center justify-between border-b border-hairline bg-canvas/80 px-4 backdrop-blur-md">
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={() => {
                    if (window.innerWidth < 768) {
                      setIsMobileSidebarOpen(true);
                    } else {
                      setIsSidebarCollapsed(false);
                    }
                  }}
                  className={cn(
                    "grid h-9 w-9 cursor-pointer place-items-center rounded-xl text-muted transition hover:bg-stone-100 hover:text-ink active:scale-95",
                    !isSidebarCollapsed && "md:hidden"
                  )}
                >
                  <PanelLeftOpen className="h-4 w-4" />
                </button>
                <div className="flex items-center gap-3">
                  {isSidebarCollapsed && (
                    <div className="flex items-center gap-2 border-r border-hairline pr-3">
                      <Sparkles className="h-4 w-4 text-primary-coral" />
                      <span className="text-xs font-bold text-ink">手搓 Agent</span>
                    </div>
                  )}
                  <span className="max-w-[140px] truncate text-sm font-semibold text-ink md:max-w-[400px]">
                    {activeSession?.title || "手搓 Agent"}
                  </span>
                </div>
              </div>
              
              <div className="flex items-center gap-2 md:gap-4">
                <div className="hidden items-center gap-3 lg:flex">
                  <div className="flex items-center gap-1.5 rounded-full bg-white px-2.5 py-1 ring-1 ring-black/[0.03] shadow-sm">
                    <div className="h-1.5 w-1.5 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.4)]" />
                    <span className="text-[10px] font-bold text-muted-soft uppercase tracking-[0.1em]">System Ready</span>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={createSession}
                  disabled={pending}
                  className="inline-flex h-9 w-9 cursor-pointer items-center justify-center rounded-xl bg-primary-coral text-white shadow-lg shadow-primary-coral/20 transition active:scale-90 disabled:cursor-not-allowed disabled:opacity-50 md:hidden"
                >
                  <Plus className="h-5 w-5" />
                </button>
              </div>
            </header>

            <main 
              ref={containerRef} 
              onScroll={handleScroll} 
              className="relative min-h-0 flex-1 overflow-y-auto scroll-smooth"
            >
              <div className="mx-auto flex min-h-full w-full max-w-4xl flex-col px-4 pb-48 pt-8 md:px-12 lg:px-16">
                {messages.length === 0 ? (
                  <section className="flex flex-1 flex-col items-center justify-center py-20 text-center">
                    <div className="mb-8 grid h-16 w-16 place-items-center rounded-2xl bg-primary-coral/5 text-primary-coral">
                      <Sparkles className="h-8 w-8" />
                    </div>
                    <h1 className="text-3xl font-bold tracking-tight text-ink md:text-4xl">有什么可以帮你的？</h1>
                    <p className="mt-4 max-w-md text-base text-body">
                      开始一段对话，或者从下方的建议开始。
                    </p>
                    <div className="mt-12 grid w-full max-w-2xl grid-cols-1 gap-3 sm:grid-cols-2">
                      {suggestions.map((suggestion) => {
                        const Icon = suggestion.icon;
                        return (
                          <button
                            key={suggestion.label}
                            type="button"
                            disabled={pending}
                            onClick={() => sendMessage(suggestion.prompt)}
                            className="group flex cursor-pointer items-center gap-4 rounded-xl border border-hairline bg-white p-4 text-left text-sm font-medium text-body shadow-sm transition-all hover:border-primary-coral/20 hover:bg-surface-soft hover:shadow-md active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50"
                          >
                            <div className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-stone-100 text-stone-500 group-hover:bg-white group-hover:text-primary-coral">
                              <Icon className="h-4 w-4" />
                            </div>
                            {suggestion.label}
                          </button>
                        );
                      })}
                    </div>
                  </section>
                ) : (
                  <div className="flex flex-col gap-8">
                    {messages.map((message) => {
                      const isUser = message.role === "user";
                      const isAssistant = message.role === "assistant";
                      
                      return (
                        <article
                          key={message.id}
                          className={cn(
                            "group relative flex w-full flex-col animate-in fade-in slide-in-from-bottom-2 duration-300",
                            isUser ? "items-end" : "items-start"
                          )}
                        >
                          <div className={cn(
                            "relative flex w-full max-w-full gap-4 md:gap-6",
                            isUser ? "flex-row-reverse" : "flex-row"
                          )}>
                            {/* 头像区域 (仅 Assistant 展示) */}
                            {!isUser && (
                              <div className="mt-1 flex h-8 w-8 shrink-0 select-none items-center justify-center rounded-lg bg-primary-coral text-white shadow-lg shadow-primary-coral/10 md:h-9 md:w-9">
                                <Layers3 className="h-5 w-5" />
                              </div>
                            )}

                            {/* 消息正文 */}
                            <div className={cn(
                              "relative min-w-0 flex-1",
                              isUser ? "flex flex-col items-end" : "flex flex-col items-start"
                            )}>
                              {isUser ? (
                                editingMessageId === message.id ? (
                                  <div className="w-full max-w-[85%] rounded-[22px] border border-hairline bg-white px-3 py-3 shadow-sm">
                                    <textarea
                                      value={editingContent}
                                      onChange={(e) => setEditingContent(e.target.value)}
                                      className="min-h-[72px] w-full resize-none border-0 bg-transparent px-1 py-0 text-[15px] leading-relaxed text-ink outline-none placeholder:text-muted-soft"
                                      rows={3}
                                      autoFocus
                                      onKeyDown={(e) => {
                                        if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                                          e.preventDefault();
                                          setEditingMessageId(null);
                                          void editAndRetryMessage(message.id, editingContent);
                                        }
                                        if (e.key === "Escape") {
                                          setEditingMessageId(null);
                                        }
                                      }}
                                    />
                                    <div className="mt-2 flex items-center justify-between gap-3 border-t border-hairline pt-2">
                                      <span className="text-[11px] text-muted-soft">Ctrl/⌘+Enter 发送</span>
                                      <div className="flex items-center gap-2">
                                        <button
                                          type="button"
                                          onClick={() => setEditingMessageId(null)}
                                          className="rounded-lg px-2.5 py-1.5 text-sm font-medium text-muted-soft transition hover:bg-stone-100 hover:text-ink"
                                        >
                                          Cancel
                                        </button>
                                        <button
                                          type="button"
                                          onClick={() => {
                                            setEditingMessageId(null);
                                            void editAndRetryMessage(message.id, editingContent);
                                          }}
                                          disabled={pending || !editingContent.trim()}
                                          className="rounded-lg bg-ink px-3 py-1.5 text-sm font-medium text-white transition hover:bg-ink/90 disabled:cursor-not-allowed disabled:opacity-50"
                                        >
                                          {pending ? "Sending..." : "Send"}
                                        </button>
                                      </div>
                                    </div>
                                  </div>
                                ) : (
                                  <div className="group/message relative max-w-[85%] rounded-2xl bg-surface-card px-4 py-2 text-[15px] leading-relaxed text-ink shadow-sm ring-1 ring-black/[0.02]">
                                    <span className="whitespace-pre-wrap break-words">{message.content}</span>
                                    <div className="absolute -bottom-9 right-1 flex items-center gap-0.5 opacity-0 transition group-hover/message:opacity-100">
                                      <button
                                        type="button"
                                        onClick={() => {
                                          navigator.clipboard.writeText(message.content);
                                          setCopiedMessageId(message.id);
                                          setTimeout(() => setCopiedMessageId(null), 2000);
                                        }}
                                        className="grid h-7 w-7 place-items-center rounded-lg text-muted-soft transition hover:bg-stone-100 hover:text-ink active:scale-90"
                                        title={copiedMessageId === message.id ? "已复制" : "复制内容"}
                                      >
                                        {copiedMessageId === message.id ? (
                                          <Check className="h-3.5 w-3.5 text-green-600" />
                                        ) : (
                                          <Copy className="h-3.5 w-3.5" />
                                        )}
                                      </button>
                                      <button
                                        type="button"
                                        onClick={() => {
                                          console.log("[pencil] clicked, setting editingMessageId=", message.id);
                                          setEditingContent(message.rawContent || message.content);
                                          setEditingMessageId(message.id);
                                        }}
                                        className="grid h-7 w-7 place-items-center rounded-lg text-muted-soft transition hover:bg-stone-100 hover:text-ink active:scale-90"
                                        title="编辑"
                                      >
                                        <Pencil className="h-3.5 w-3.5" />
                                      </button>
                                    </div>
                                  </div>
                                )
                              ) : (
                                <div className="w-full">
                                  <div className="markdown-body">
                                    <MarkdownMessage content={message.content} />
                                    {message.status === "streaming" && (
                                      <span className="inline-block h-4 w-1 animate-pulse bg-primary-coral align-middle ml-1" />
                                    )}
                                  </div>
                                  
                                  {message.status === "streaming" && !message.content && (
                                    <div className="flex items-center gap-2 py-2 text-sm font-medium text-muted-soft">
                                      <Loader2 className="h-3.5 w-3.5 animate-spin text-primary-coral" />
                                      Agent 正在思考...
                                    </div>
                                  )}

                                  {message.status === "stopped" && (
                                    <div className="mt-4 inline-flex items-center gap-1.5 rounded-full bg-rose-50 px-2.5 py-0.5 text-[10px] font-bold text-rose-500 uppercase tracking-wider ring-1 ring-rose-500/10">
                                      Generation Stopped
                                    </div>
                                  )}

                                  {message.status === "retrying" && (
                                    <div className="mt-4 inline-flex items-center gap-1.5 rounded-full bg-amber-50 px-2.5 py-0.5 text-[10px] font-bold text-amber-600 uppercase tracking-wider ring-1 ring-amber-500/10">
                                      Rolling Back...
                                    </div>
                                  )}

                                  {message.status === "rolled_back" && (
                                    <div className="mt-4 inline-flex items-center gap-1.5 rounded-full bg-stone-100 px-2.5 py-0.5 text-[10px] font-bold text-stone-500 uppercase tracking-wider ring-1 ring-stone-300/60">
                                      Rolled Back
                                    </div>
                                  )}

                                  {/* 消息 Meta 信息 & 工具步骤 */}
                                  <div className="mt-6 flex flex-col gap-4 empty:hidden">
                                    {message.steps && message.steps.length > 0 && (
                                      <ToolSteps steps={message.steps} onAction={sendMessage} disabled={pending} />
                                    )}

                                    {message.artifacts && message.artifacts.length > 0 && (
                                      <RuntimeArtifacts artifacts={message.artifacts} />
                                    )}
                                    
                                    {(message.runtime ||
                                      message.model ||
                                      (message.steps && message.steps.length > 0) ||
                                      (message.artifacts && message.artifacts.length > 0)) && (
                                      <div className="flex items-center gap-3 text-[10px] font-bold text-muted-soft uppercase tracking-widest opacity-60 transition-opacity group-hover:opacity-100">
                                        {message.runtime && (
                                          <span className="flex items-center gap-1">
                                            <Layers3 className="h-3 w-3" />
                                            {runtimes.find((runtime) => runtime.id === message.runtime)?.label || message.runtime}
                                          </span>
                                        )}
                                        {message.model && (
                                          <span className="flex items-center gap-1">
                                            <Sparkles className="h-3 w-3" />
                                            {models.find((model) => model.id === message.model)?.label || message.model}
                                          </span>
                                        )}
                                        {message.steps && message.steps.length > 0 && (
                                          <span className="flex items-center gap-1">
                                            <Terminal className="h-3 w-3" />
                                            {message.steps.length} Tool Actions
                                          </span>
                                        )}
                                        {message.artifacts && message.artifacts.length > 0 && (
                                          <span className="flex items-center gap-1">
                                            <Archive className="h-3 w-3" />
                                            {message.artifacts.length} Artifacts
                                          </span>
                                        )}
                                      </div>
                                    )}
                                  </div>
                                </div>
                              )}
                            </div>

                            {/* 操作栏 (Hover 触发) */}
                            <div className={cn(
                              "absolute -bottom-8 flex items-center gap-1 opacity-0 transition-all duration-200 group-hover:bottom-[-2.5rem] group-hover:opacity-100",
                              isUser ? "hidden" : "left-12 md:left-15"
                            )}>
                              <button 
                                onClick={() => {
                                  navigator.clipboard.writeText(message.content);
                                  setCopiedMessageId(message.id);
                                  setTimeout(() => setCopiedMessageId(null), 2000);
                                }}
                                className="grid h-8 w-8 cursor-pointer place-items-center rounded-lg text-muted-soft transition hover:bg-stone-100 hover:text-ink active:scale-90"
                                title={copiedMessageId === message.id ? "已复制" : "复制内容"}
                              >
                                {copiedMessageId === message.id ? (
                                  <Check className="h-3.5 w-3.5 text-green-600" />
                                ) : (
                                  <Copy className="h-3.5 w-3.5" />
                                )}
                              </button>
                              {isAssistant && message.status === "done" && (
                                <>
                                  <div className="relative">
                                    <button 
                                      onClick={() => setRetryConfirmMessageId((current) => (current === message.id ? null : message.id))}
                                      disabled={!message.turnId || retryingTurnId === message.turnId}
                                      className="grid h-8 w-8 cursor-pointer place-items-center rounded-lg text-muted-soft transition hover:bg-stone-100 hover:text-ink active:scale-90 disabled:cursor-not-allowed disabled:opacity-40" 
                                      title="回滚并重试"
                                    >
                                      <RotateCcw className="h-3.5 w-3.5" />
                                    </button>
                                    {retryConfirmMessageId === message.id && (
                                      <div className="absolute bottom-10 left-0 z-20 w-56 rounded-xl border border-hairline bg-white p-3 shadow-xl">
                                        <div className="text-xs font-medium text-ink">
                                          {message.runtime === "handmade" 
                                            ? "回滚本轮文件修改后重新执行。"
                                            : "重新执行本轮对话（外部 Agent 的文件变更无法自动回滚）。"}
                                        </div>
                                        <div className="mt-2 flex justify-end gap-2">
                                          <button
                                            type="button"
                                            onClick={() => setRetryConfirmMessageId(null)}
                                            className="rounded-lg px-2.5 py-1.5 text-xs font-medium text-muted-soft transition hover:bg-stone-100 hover:text-ink"
                                          >
                                            取消
                                          </button>
                                          <button
                                            type="button"
                                            onClick={() => void retryTurn(message)}
                                            className="rounded-lg bg-ink px-2.5 py-1.5 text-xs font-medium text-white transition hover:bg-ink/90"
                                          >
                                            确认
                                          </button>
                                        </div>
                                      </div>
                                    )}
                                  </div>
                                </>
                              )}
                            </div>
                          </div>
                        </article>
                      );
                    })}
                  </div>
                )}
                <div ref={scrollRef} className="h-12" />
              </div>

              {showScrollButton && (
                <div className="sticky bottom-6 flex justify-center z-30 pointer-events-none">
                  <button
                    type="button"
                    onClick={scrollToBottom}
                    className={cn(
                      "pointer-events-auto flex items-center gap-2 rounded-full border border-hairline bg-white/95 px-4 py-2 text-[11px] font-bold text-ink shadow-lg backdrop-blur-sm transition-all hover:-translate-y-0.5 active:scale-95 animate-in fade-in zoom-in-95 duration-200",
                      hasUnread && !pending ? "border-primary-coral/20 bg-primary-coral/5 text-primary-coral ring-4 ring-primary-coral/5" : ""
                    )}
                  >
                    {pending ? (
                      <span className="flex items-center gap-2">
                        <Loader2 className="h-3 w-3 animate-spin text-primary-coral" />
                        <span className="uppercase tracking-widest">Generating ↓</span>
                      </span>
                    ) : (
                      <span className="flex items-center gap-2 uppercase tracking-widest">
                        {hasUnread ? "New Messages ↓" : "Back to Bottom ↓"}
                      </span>
                    )}
                  </button>
                </div>
              )}
            </main>

            <div className="sticky bottom-0 z-20 shrink-0">
              <div className="pointer-events-none absolute inset-x-0 bottom-0 h-40 bg-gradient-to-t from-canvas via-canvas/95 to-transparent" />
              
              <div className="relative z-30 mx-auto w-full max-w-4xl px-4 pb-4 md:pb-10 md:px-12 lg:px-16 pb-[calc(1rem+env(safe-area-inset-bottom))]">
                <div className="relative flex flex-col rounded-[20px] border border-hairline bg-white shadow-[0_8px_30px_rgb(0,0,0,0.04),0_0_0_1px_rgba(0,0,0,0.01)] transition-all duration-300 focus-within:border-primary-coral/40 focus-within:ring-4 focus-within:ring-primary-coral/5">
                  <form onSubmit={onSubmit} className="flex flex-col">
                    <textarea
                      value={input}
                      onChange={(event) => setInput(event.target.value)}
                      onCompositionStart={() => setIsComposing(true)}
                      onCompositionEnd={() => setIsComposing(false)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" && !event.shiftKey && !isComposing) {
                          event.preventDefault();
                          if (input.trim() && selectedModelId && selectedRuntimeId && !pending) {
                            event.currentTarget.form?.requestSubmit();
                          }
                        }
                      }}
                      rows={1}
                      placeholder={loadError || "给 Agent 发消息..."}
                      className="block max-h-60 min-h-[56px] w-full resize-none bg-transparent px-5 py-4 text-[15px] leading-relaxed text-ink outline-none placeholder:text-muted-soft md:min-h-[64px]"
                    />
                    
                    <div className="flex flex-col border-t border-stone-50/50 px-3 py-2 sm:flex-row sm:items-center sm:justify-between">
                      <div className="flex flex-wrap items-center gap-1">
                        <RuntimePicker
                          runtimes={runtimes}
                          selectedRuntimeId={selectedRuntimeId}
                          onSelect={selectRuntime}
                        />
                        
                        <div className="hidden h-4 w-px bg-hairline sm:block mx-1" />
                        
                        <ModelPicker models={models} selectedModelId={selectedModelId} onSelect={selectModel} />
                        
                        <div className="hidden h-4 w-px bg-hairline sm:block mx-1" />
                        
                        <button
                          type="button"
                          className="group flex items-center gap-1.5 rounded-lg px-2 py-1 text-muted-soft transition hover:bg-stone-100 hover:text-ink active:scale-95"
                          title="工具管理"
                        >
                          <Settings2 className="h-3.5 w-3.5" />
                          <span className="text-[11px] font-bold uppercase tracking-widest">Tools</span>
                        </button>
                        
                        <button
                          type="button"
                          className="grid h-8 w-8 cursor-pointer place-items-center rounded-lg text-muted-soft transition hover:bg-stone-100 hover:text-ink active:scale-95"
                          title="上传附件"
                        >
                          <Paperclip className="h-3.5 w-3.5" />
                        </button>
                      </div>

                      <div className="mt-2 flex items-center justify-between gap-3 sm:mt-0 sm:justify-end">
                        {input.length > 0 && (
                          <span className="text-[10px] font-bold text-muted-soft uppercase tracking-widest tabular-nums">
                            {input.length} chars
                          </span>
                        )}
                        <button
                          type={pending ? "button" : "submit"}
                          disabled={pending ? false : !input.trim() || !selectedModelId || !selectedRuntimeId}
                          aria-label={pending ? "停止生成" : "发送"}
                          onClick={pending ? stopGeneration : undefined}
                          className={cn(
                            "grid h-8 w-8 cursor-pointer place-items-center rounded-xl transition-all active:scale-90 disabled:cursor-not-allowed disabled:opacity-10 shadow-sm",
                            pending ? "bg-rose-500 text-white shadow-rose-200" : "bg-ink text-white hover:bg-stone-800 shadow-stone-200"
                          )}
                        >
                          {pending ? <Square className="h-3.5 w-3.5 fill-current" /> : <ArrowUp className="h-4 w-4" />}
                        </button>
                      </div>
                    </div>
                  </form>
                </div>
                <p className="mt-4 text-center text-[10px] font-bold text-muted-soft uppercase tracking-[0.15em] opacity-40 hidden sm:block">
                  Agent may display inaccurate info · version 1.0.4-rc
                </p>
              </div>
            </div>
          </div>

          <RuntimeWorkbenchPanel
            artifacts={latestAssistantMessage?.artifacts || []}
            sessionRef={latestAssistantMessage?.sessionRef || null}
            runtimeLabel={activeRuntime?.label || latestAssistantMessage?.runtime || activeSession?.runtimeId || selectedRuntimeId}
            modelLabel={activeModel?.label || latestAssistantMessage?.model || activeSession?.modelId || selectedModelId}
            loading={artifactRefreshing}
            onRefresh={() => void refreshRuntimeArtifacts()}
          />
        </>
      ) : (
        <div className="flex-1 overflow-hidden">
          <SkillManagerView />
        </div>
      )}
    </div>
  );
}
