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
};

export type ToolStep = {
  type: "tool" | "tool_error" | string;
  tool: string;
  args: Record<string, unknown>;
  result: unknown;
};

export type AgentResponse = {
  answer: string;
  steps: ToolStep[];
  model?: string;
};
