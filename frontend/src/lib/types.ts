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
  runtime?: string;
  source?: string;
  editable?: boolean;
  native?: boolean;
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
  runtime?: string;
  trace_id?: string;
};

export type RuntimeSessionRef = {
  local_session_id?: string;
  runtime_session_id?: string;
  workspace?: string;
};

export type RuntimeArtifact = {
  protocol_version?: "runtime-artifact.v1" | string;
  id: string;
  type: "tool_call" | "command_output" | "file_diff" | "todo" | "permission" | "diagnostic" | "trace" | "file" | "link" | string;
  runtime?: string;
  title?: string;
  status?: "ready" | "running" | "error" | string;
  data?: unknown;
  updated_at?: number;
};

export type RuntimeEventName =
  | "message_start"
  | "text_delta"
  | "tool_start"
  | "tool_result"
  | "tool_error"
  | "artifact_updated"
  | "session_diff"
  | "session_todo"
  | "session_status"
  | "message_done"
  | "error";

export type RuntimeEventPayload = {
  protocol_version?: "runtime-event.v1" | string;
  event?: RuntimeEventName | string;
  event_id?: string;
  sequence?: number;
  created_at?: number;
  runtime?: string;
  trace_id?: string;
  turn_id?: string;
  model?: string;
  answer?: string;
  delta?: string;
  steps?: ToolStep[];
  artifacts?: RuntimeArtifact[];
  artifact?: RuntimeArtifact;
  session_ref?: RuntimeSessionRef | null;
  message?: string;
  [key: string]: unknown;
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

export type RuntimeCatalogOption = RuntimeOption & {
  tools?: ToolOption[];
  skills?: SkillOption[];
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
  type: "hook" | "invocable" | "native" | string;
  paths: string[];
  trigger_words: string[];
  instructions: string;
  runtime?: string;
  source?: string;
  source_detail?: string;
  scope?: "project" | "user" | "admin" | "configured" | string;
  standard?: string;
  path?: string;
  skill_dir?: string;
  frontmatter?: Record<string, unknown>;
  editable?: boolean;
  native?: boolean;
  content_truncated?: boolean;
};
