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
}

export async function fetchCaseDraftPaymentStatus(
  caseDraftId: string
): Promise<CaseDraftPaymentStatus> {
  const res = await api.get<CaseDraftPaymentStatus>(
    `/payments/case-drafts/${encodeURIComponent(caseDraftId)}/status`
  );
  return res.data;
}
