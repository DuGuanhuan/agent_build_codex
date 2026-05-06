export type ChatRole = "user" | "assistant";

export type ChatMessage = {
  role: ChatRole;
  content: string;
};

export type ModelOption = {
  id: string;
  label: string;
  provider: string;
  model: string;
  thinking: "enabled" | "disabled" | string;
  description: string;
  available: boolean;
  default: boolean;
  context_window_tokens: number;
  reserved_output_tokens: number;
  available_input_tokens: number;
};

export type ToolOption = {
  name: string;
  description: string;
  permission: string;
  parameters: {
    type: string;
    required?: string[];
    properties?: Record<string, unknown>;
  };
};

export type ToolStep = {
  type: "tool" | "tool_error" | string;
  id?: string;
  status?: "pending" | "running" | "success" | "error" | "skipped" | "cancelled" | "awaiting_approval" | string;
  tool: string;
  args: Record<string, unknown>;
  result?: unknown;
  error?: string | null;
  permission?: string | null;
  started_at?: number;
  ended_at?: number | null;
  duration_ms?: number | null;
};

export type RuntimeSessionRef = {
  local_session_id?: string;
  runtime_session_id?: string;
  workspace?: string;
};

export type RuntimeArtifact = {
  id: string;
  type: "tool_call" | "command_output" | "file_diff" | "todo" | "permission" | "diagnostic" | "trace" | "file" | "link" | string;
  runtime?: string;
  title?: string;
  status?: "ready" | "running" | "error" | string;
  data?: unknown;
};

export type RuntimeCapabilities = {
  text?: boolean;
  stream?: boolean;
  reasoning?: boolean;
  toolEvents?: boolean;
  toolDelta?: boolean;
  toolApproval?: boolean;
  fileRead?: boolean;
  fileWrite?: boolean;
  shell?: boolean;
  webFetch?: boolean;
  webSearch?: boolean;
  subAgent?: boolean;
  diff?: boolean;
  todo?: boolean;
  nativeSession?: boolean;
  abort?: boolean;
  resume?: boolean;
  compare?: boolean;
  workspaceOnly?: boolean;
  rawEvents?: boolean;
};

export type RuntimeOption = {
  id: string;
  label: string;
  description: string;
  available: boolean;
  default: boolean;
  version?: string | null;
  unavailable_reason?: string;
  capabilities: RuntimeCapabilities;
  supported_model_ids?: string[];
};

export type AgentResponse = {
  answer: string;
  steps: ToolStep[];
  artifacts?: RuntimeArtifact[];
  model?: string;
  runtime?: string;
  trace_id?: string;
};
export type SkillOption = {
  name: string;
  description: string;
  type: "hook" | "invocable";
  paths: string[];
  trigger_words: string[];
  instructions: string;
};
