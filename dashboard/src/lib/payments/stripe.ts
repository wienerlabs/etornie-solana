import api from "@/lib/api";

export interface StripeConfig {
  publishable_key: string;
  api_version: string;
}

export interface CheckoutSessionResponse {
  payment_intent_id: string;
  checkout_session_id: string;
  checkout_url: string;
  amount: string;
  currency: string;
  expires_at: number;
}

export interface PaymentIntent {
  id: string;
  case_draft_id: string;
  payment_type: string;
  provider: string;
  amount: string;
  currency: string;
  status:
    | "created"
    | "awaiting"
    | "confirmed"
    | "failed"
    | "refunded"
    | "expired";
  gateway_payment_id: string | null;
}

export async function fetchStripeConfig(): Promise<StripeConfig> {
  const res = await api.get<StripeConfig>("/payments/stripe/config");
  return res.data;
}

export async function createStripeCheckoutSession(input: {
  caseDraftId: string;
  platform: "EUIPO" | "WIPO" | "USPTO" | "UKIPO";
}): Promise<CheckoutSessionResponse> {
  const res = await api.post<CheckoutSessionResponse>(
    "/payments/stripe/checkout-session",
    {
      case_draft_id: input.caseDraftId,
      platform: input.platform,
    }
  );
  return res.data;
}

export async function reconcileStripeSession(
  sessionId: string
): Promise<PaymentIntent> {
  const res = await api.get<PaymentIntent>(
    `/payments/stripe/sessions/${encodeURIComponent(sessionId)}/status`
  );
  return res.data;
}

export interface CaseDraftPaymentStatus {
  case_draft_id: string;
  draft_status: string;
  paid: boolean;
  pending: boolean;
  confirmed_intent_id: string | null;
  confirmed_provider: string | null;
  confirmed_amount: string | null;
  confirmed_currency: string | null;
  filing_attempt_id: string | null;
  filing_status: string | null;
  filing_external_reference: string | null;
  filing_error: string | null;
  compliance_artifact_id: string | null;
  compliance_status: string | null;
  compliance_onchain_tx: string | null;
  case_id: string | null;
  case_number: string | null;
}

export async function fetchCaseDraftPaymentStatus(
  caseDraftId: string
): Promise<CaseDraftPaymentStatus> {
  const res = await api.get<CaseDraftPaymentStatus>(
    `/payments/case-drafts/${encodeURIComponent(caseDraftId)}/status`
  );
  return res.data;
}

export interface UkipoCheckoutSessionResponse {
  submission_id: string;
  checkout_session_id: string;
  checkout_url: string;
  amount_minor: number;
  currency: string;
}

export async function createUkipoStripeCheckoutSession(
  submissionId: string,
): Promise<UkipoCheckoutSessionResponse> {
  const res = await api.post<UkipoCheckoutSessionResponse>(
    "/payments/stripe/ukipo-checkout-session",
    { submission_id: submissionId },
  );
  return res.data;
}
