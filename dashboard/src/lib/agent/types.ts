// Shared types for the EtornieGPT agent surface. Keep these aligned
// with the Pydantic schemas in services/api/app/agent/schemas.py.

export type AgentRole = "user" | "assistant" | "tool";
export type AgentStatus = "active" | "archived";

export interface AgentSession {
  id: string;
  title: string | null;
  status: AgentStatus;
  model: string;
  total_input_tokens: number;
  total_output_tokens: number;
  started_at: string;
  last_activity_at: string;
}

export interface AgentMessage {
  id: string;
  role: AgentRole;
  content: string | null;
  tool_call_id: string | null;
  tool_name: string | null;
  tool_arguments: Record<string, unknown> | null;
  tool_result: Record<string, unknown> | null;
  created_at: string;
}

export interface SessionListResponse {
  sessions: AgentSession[];
}

export interface MessageListResponse {
  messages: AgentMessage[];
}

export interface TurnResponse {
  session: AgentSession;
  messages: AgentMessage[];
}

export type FilingStatus =
  | "pending"
  | "running"
  | "awaiting_payment"
  | "filed"
  | "failed";

export interface FilingProgress {
  submission_id: string;
  status: FilingStatus;
  current_step: string | null;
  error_step: string | null;
  error_message: string | null;
  ipo_application_url: string | null;
  ipo_reference: string | null;
  owner_company_name: string;
  owner_country: string;
  mark_text: string | null;
  mark_type: string;
  nice_classes: Array<{ class_number: number; description: string }>;
  started_at: string | null;
  finished_at: string | null;
}

// User-facing labels for each robot step. Keep aligned with STEPS in
// services/api/app/services/ukipo/robot.py.
export const STEP_LABELS: Record<string, string> = {
  open_form: "Opening application form",
  choose_representative_role: "Selecting representative role",
  fill_representative_details: "Filling representative details",
  fill_owner_details: "Filling owner details",
  choose_mark_type: "Choosing mark type",
  single_trade_mark: "Selecting single trade mark",
  select_class_manually: "Selecting Nice classes manually",
  enter_nice_classes: "Entering Nice class descriptions",
  confirm_bottom_option: "Confirming declaration option",
  answer_no_questions: "Answering form questions",
  choose_standard_mark: "Choosing standard mark",
  choose_examination_type: "Choosing examination type",
  declaration: "Filled declaration screen",
  reach_payment_screen: "Reached payment selection",
};

export const STATUS_LABELS: Record<FilingStatus, string> = {
  pending: "Pending",
  running: "Robot running",
  awaiting_payment: "Awaiting payment",
  filed: "Filed",
  failed: "Failed",
};
