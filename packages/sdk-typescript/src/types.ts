// Domain types mirroring the Etornie API response shapes for the core
// resources the SDK covers. Optional fields use `| null` to match the
// API's JSON (nullable columns serialise to null).

export type CaseType = "trademark" | "patent" | "design" | "copyright";
export type CaseStatus = "open" | "in_progress" | "under_review" | "closed";
export type CaseNftState = "none" | "pending_claim" | "minted" | "burned";
export type DocumentStatus = string;
export type UserRole = "admin" | "client";

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface User {
  id: string;
  email: string | null;
  full_name: string;
  phone: string | null;
  role: UserRole;
  is_active: boolean;
  wallet_address: string | null;
  public_handle: string | null;
  auth_method: string;
  created_at: string;
  updated_at: string;
}

export interface Case {
  id: string;
  title: string;
  description: string | null;
  case_number: string;
  case_type: CaseType;
  status: CaseStatus;
  client_id: string | null;
  assigned_lawyer_id: string | null;
  jurisdiction: string | null;
  nice_classes: string | null;
  filing_date: string | null;
  deadline: string | null;
  deadline_time: string | null;
  created_at: string;
  updated_at: string;
  attestation_tx: string | null;
  attestation_pda: string | null;
  client_wallet: string | null;
  nft_mint: string | null;
  nft_state: CaseNftState;
}

export interface CaseListResponse {
  cases: Case[];
  total: number;
}

export interface CreateCaseInput {
  title: string;
  case_type: CaseType;
  description?: string | null;
  client_id?: string | null;
  client_wallet?: string | null;
  guest_client_name?: string | null;
  guest_client_email?: string | null;
  guest_client_phone?: string | null;
  assigned_lawyer_id?: string | null;
  jurisdiction?: string | null;
  nice_classes?: string | null;
  filing_date?: string | null;
  deadline?: string | null;
  deadline_time?: string | null;
}

export interface UpdateCaseInput {
  title?: string;
  description?: string | null;
  case_type?: CaseType;
  status?: CaseStatus;
  assigned_lawyer_id?: string | null;
  jurisdiction?: string | null;
  nice_classes?: string | null;
  filing_date?: string | null;
  deadline?: string | null;
  deadline_time?: string | null;
}

export interface CaseDocument {
  id: string;
  case_id: string;
  uploaded_by: string;
  filename: string;
  file_type: string | null;
  file_size: number | null;
  status: DocumentStatus;
  document_type: string | null;
  created_at: string;
}

export interface DocumentListResponse {
  documents: CaseDocument[];
  total: number;
}

export interface RenewalReminderRow {
  window_days: number;
  target_due_at: string;
  sent_at: string;
  channels: string[];
}

export interface RenewalStatus {
  case_id: string;
  renewal_due_at: string | null;
  days_remaining: number | null;
  is_overdue: boolean;
  open_window: number | null;
  reminders: RenewalReminderRow[];
}

export interface CalendarFeedStatus {
  enabled: boolean;
  url: string | null;
}

export type DataExportFormat = "json" | "pdf" | "docx" | "xlsx";

export interface ListCasesParams {
  skip?: number;
  limit?: number;
  status?: CaseStatus;
}
