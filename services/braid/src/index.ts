import 'dotenv/config'
import { Agent, run } from '@openserv-labs/sdk'
import { z } from 'zod'

import { addAuditedCapability } from './audit.js'

const apiKey = process.env.OPENSERV_API_KEY
if (!apiKey) {
  console.error(
    '[braid] OPENSERV_API_KEY is missing. Copy .env.example to .env and fill it in.'
  )
  process.exit(1)
}

const SYSTEM_PROMPT = `You are the reasoning layer for Etornie, a regulated IP filing and on-chain compliance platform on Solana.

Your domain:
- Trademark and IP filings across multiple jurisdictions (UKIPO, EUIPO, IP Australia, WIPO)
- Zero-knowledge file-ownership proofs (file_ownership circuit, on-chain ZK verifier)
- x402 micropayment validation for paid agent workflows
- Document compliance scoring and jurisdictional routing

Operating principles:
1. Never assume facts. Use the available capabilities to verify ZK proofs, fetch document metadata, validate payment headers, and check jurisdictional rules before forming a conclusion.
2. Decompose every decision into explicit, ordered steps. For each step name the capability used, the inputs, the result, and the inference drawn.
3. When multiple jurisdictions or compliance paths apply, list the alternatives and rank them with explicit criteria. Do not silently pick one.
4. If a required capability fails, returns ambiguous data, or the input violates a hard constraint (missing payment, invalid proof, prohibited jurisdiction), STOP and request human assistance. Do not paper over uncertainty with plausible-sounding text.
5. Every decision must be reproducible from the trace alone — assume a regulator or auditor will read it later.
6. Default to the most conservative compliance interpretation when rules conflict.

You will be invoked from Etornie's backend. Capability outputs are authoritative; your role is to reason over them, not invent them.`

// SDK 2.4.1 respondToChat reads action.messages as {author, message}, but the
// runtime now sends {role, content}. Normalize before delegating to super so
// the user's message reaches the runtime instead of being dropped.
class EtornieAgent extends Agent {
  protected override async respondToChat(action: unknown): Promise<void> {
    const a = action as {
      messages?: Array<Record<string, unknown>>
    }
    if (Array.isArray(a.messages)) {
      a.messages = a.messages.map(msg => {
        const role = msg.role ?? msg.author
        const content = msg.content ?? msg.message ?? ''
        return {
          ...msg,
          author: role === 'user' ? 'user' : 'agent',
          message: typeof content === 'string' ? content : JSON.stringify(content)
        }
      })
    }
    return super.respondToChat(action as Parameters<Agent['respondToChat']>[0])
  }
}

const agent = new EtornieAgent({
  systemPrompt: SYSTEM_PROMPT
})

addAuditedCapability(agent, {
  name: 'ping',
  description:
    'Health check capability. Returns a confirmation payload with timestamp. Use this to verify the agent is reachable and that BRAID can dispatch a capability call end-to-end.',
  inputSchema: z.object({
    note: z
      .string()
      .optional()
      .describe('Optional note to echo back in the response')
  }),
  async run({ args }) {
    return JSON.stringify({
      status: 'ok',
      service: 'etornie-braid',
      version: '0.0.1',
      timestamp: new Date().toISOString(),
      echo: args.note ?? null
    })
  }
})

const ETORNIE_API_BASE_URL =
  process.env.ETORNIE_API_BASE_URL ?? 'http://localhost:8000'
const BRAID_INTERNAL_TOKEN = process.env.BRAID_INTERNAL_TOKEN ?? ''

addAuditedCapability(agent, {
  name: 'verify_x402_payment',
  description:
    'Verify an x402 SOL micropayment for an EtornieGPT query. Checks that the payment tx exists on Solana devnet, succeeded, moved at least the minimum lamports to the EtornieGPT vault, and carries the expected memo binding. Returns a structured verification result. Use this BEFORE acting on any paid EtornieGPT request — if verified=false, do not proceed with the paid response and request human assistance with the error message.',
  inputSchema: z.object({
    signature: z
      .string()
      .min(43)
      .max(96)
      .describe('Solana transaction signature (base58) of the user payment'),
    expected_memo: z
      .string()
      .min(1)
      .describe(
        'Memo string the payment must carry. Typically base58(sha256(query_hash || commitment)) produced by the EtornieGPT chat handler.'
      ),
    min_lamports: z
      .number()
      .int()
      .positive()
      .optional()
      .describe(
        'Minimum lamports required. Defaults to the platform setting if omitted.'
      ),
    recipient_vault: z
      .string()
      .optional()
      .describe(
        'Expected recipient vault pubkey. Defaults to the platform setting if omitted.'
      )
  }),
  async run({ args }) {
    if (!BRAID_INTERNAL_TOKEN) {
      return JSON.stringify({
        verified: false,
        error:
          'BRAID_INTERNAL_TOKEN missing in services/braid/.env — cannot reach Etornie API',
        capability: 'verify_x402_payment'
      })
    }

    let response: Response
    try {
      response = await fetch(
        `${ETORNIE_API_BASE_URL}/braid/verify-x402-payment`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-Braid-Auth': BRAID_INTERNAL_TOKEN
          },
          body: JSON.stringify(args)
        }
      )
    } catch (err) {
      return JSON.stringify({
        verified: false,
        error: `etornie api unreachable at ${ETORNIE_API_BASE_URL}: ${
          err instanceof Error ? err.message : String(err)
        }`,
        capability: 'verify_x402_payment'
      })
    }

    const text = await response.text()
    if (!response.ok) {
      return JSON.stringify({
        verified: false,
        error: `etornie api ${response.status}: ${text || 'empty body'}`,
        capability: 'verify_x402_payment'
      })
    }

    return text
  }
})

addAuditedCapability(agent, {
  name: 'verify_zk_file_ownership',
  description:
    'Verify on-chain that a file_ownership ZK proof exists for a given (user_wallet, file_hash) pair on Solana devnet. Derives the FileOwnershipRecord PDA, fetches its account info via RPC, and returns a structured outcome (verified=true if a properly sized Anchor account exists; verified=false with a precise reason otherwise — invalid pubkey, malformed file hash, no proof on-chain, RPC unreachable, etc.). Use BEFORE acting on any document-ownership claim. If verified=false because no proof was submitted, do not invent ownership; either reject the claim or request human assistance with the exact PDA and explorer URL.',
  inputSchema: z.object({
    user_wallet: z
      .string()
      .min(32)
      .max(44)
      .describe('Base58 Solana pubkey of the claimed file owner'),
    file_hash_hex: z
      .string()
      .length(64)
      .regex(
        /^[0-9a-fA-F]+$/,
        'file_hash_hex must be 64 hex characters (32 bytes)'
      )
      .describe(
        'Hex-encoded SHA-256 digest (32 bytes) of the file whose ownership is being verified'
      )
  }),
  async run({ args }) {
    if (!BRAID_INTERNAL_TOKEN) {
      return JSON.stringify({
        error:
          'BRAID_INTERNAL_TOKEN missing in services/braid/.env — cannot reach Etornie API',
        capability: 'verify_zk_file_ownership'
      })
    }

    let response: Response
    try {
      response = await fetch(
        `${ETORNIE_API_BASE_URL}/braid/verify-zk-file-ownership`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-Braid-Auth': BRAID_INTERNAL_TOKEN
          },
          body: JSON.stringify(args)
        }
      )
    } catch (err) {
      return JSON.stringify({
        error: `etornie api unreachable at ${ETORNIE_API_BASE_URL}: ${
          err instanceof Error ? err.message : String(err)
        }`,
        capability: 'verify_zk_file_ownership'
      })
    }

    const text = await response.text()
    if (!response.ok) {
      return JSON.stringify({
        error: `etornie api ${response.status}: ${text || 'empty body'}`,
        capability: 'verify_zk_file_ownership'
      })
    }

    return text
  }
})

addAuditedCapability(agent, {
  name: 'score_document_completeness',
  description:
    'Score how ready an Etornie case is for filing by checking its required-document checklist against jurisdiction rules. Takes a case_id (UUID) and returns a breakdown by status (pending / uploaded / approved / rejected / cancelled), completeness_pct (approved/required), ready_to_file flag, and the list of missing documents with their current status. Use this BEFORE recommending or initiating any office submission. If ready_to_file=false, never recommend submission — list the missing items and request they be uploaded/approved first.',
  inputSchema: z.object({
    case_id: z
      .string()
      .uuid()
      .describe('Etornie case UUID whose document checklist should be scored')
  }),
  async run({ args }) {
    if (!BRAID_INTERNAL_TOKEN) {
      return JSON.stringify({
        error:
          'BRAID_INTERNAL_TOKEN missing in services/braid/.env — cannot reach Etornie API',
        capability: 'score_document_completeness'
      })
    }

    let response: Response
    try {
      response = await fetch(
        `${ETORNIE_API_BASE_URL}/braid/score-document-completeness`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-Braid-Auth': BRAID_INTERNAL_TOKEN
          },
          body: JSON.stringify({ case_id: args.case_id })
        }
      )
    } catch (err) {
      return JSON.stringify({
        error: `etornie api unreachable at ${ETORNIE_API_BASE_URL}: ${
          err instanceof Error ? err.message : String(err)
        }`,
        capability: 'score_document_completeness'
      })
    }

    const text = await response.text()
    if (!response.ok) {
      return JSON.stringify({
        error: `etornie api ${response.status}: ${text || 'empty body'}`,
        capability: 'score_document_completeness'
      })
    }

    return text
  }
})

addAuditedCapability(agent, {
  name: 'route_office_response',
  description:
    'Classify ONE inbound communication from an IP office (UKIPO / EUIPO / IP Australia / WIPO) into a structured routing decision: classification (acceptance, provisional_refusal, opposition_notice, examination_report, registration_certificate, fee_request, status_update, withdrawal_acknowledgment, office_action_request, unknown), urgency, deadline_iso, recommended_action, extracted_entities (application_number, mark_name, opposition_basis, nice_classes, opponent), requires_attorney_review flag, and escalation_required flag. Use this on EVERY raw office response BEFORE deciding next steps. Powered by Together AI gpt-oss-20b on the Etornie backend.',
  inputSchema: z.object({
    response_text: z
      .string()
      .min(1)
      .max(12000)
      .describe('Raw text of the office response (extracted from PDF, email body, etc.)'),
    office: z
      .enum(['ukipo', 'euipo', 'ipau', 'wipo', 'unknown'])
      .optional()
      .describe('IP office that sent the response (default: unknown)'),
    case_id: z
      .string()
      .max(64)
      .optional()
      .describe('Etornie internal case identifier this response belongs to'),
    language: z
      .string()
      .max(16)
      .optional()
      .describe('Language hint (ISO code) or "auto"')
  }),
  async run({ args }) {
    if (!BRAID_INTERNAL_TOKEN) {
      return JSON.stringify({
        error:
          'BRAID_INTERNAL_TOKEN missing in services/braid/.env — cannot reach Etornie API',
        capability: 'route_office_response'
      })
    }

    const payload = {
      response_text: args.response_text,
      office: args.office ?? 'unknown',
      case_id: args.case_id ?? null,
      language: args.language ?? null
    }

    let response: Response
    try {
      response = await fetch(
        `${ETORNIE_API_BASE_URL}/braid/route-office-response`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-Braid-Auth': BRAID_INTERNAL_TOKEN
          },
          body: JSON.stringify(payload)
        }
      )
    } catch (err) {
      return JSON.stringify({
        error: `etornie api unreachable at ${ETORNIE_API_BASE_URL}: ${
          err instanceof Error ? err.message : String(err)
        }`,
        capability: 'route_office_response'
      })
    }

    const text = await response.text()
    if (!response.ok) {
      return JSON.stringify({
        error: `etornie api ${response.status}: ${text || 'empty body'}`,
        capability: 'route_office_response'
      })
    }

    return text
  }
})

addAuditedCapability(agent, {
  name: 'triage_customer_message',
  description:
    'Classify ONE inbound customer message (WhatsApp / email / web chat) into a structured intent + urgency + entity extraction. Returns classification (one of new_filing_request, existing_case_inquiry, office_response_forwarded, objection_or_dispute, billing_question, support_request, spam_or_irrelevant, urgent_legal_deadline), urgency (low/medium/high/critical), recommended_action, detected_entities (case_id, jurisdiction, trademark_name, deadline) and an escalation_required flag. Use this on EVERY raw user message before deciding what to do with it; do not invent classifications without calling this. Powered by Together AI gpt-oss-20b on the Etornie backend.',
  inputSchema: z.object({
    message_text: z
      .string()
      .min(1)
      .max(8000)
      .describe('Raw customer message text to classify'),
    channel: z
      .enum(['whatsapp', 'email', 'web_chat', 'unknown'])
      .optional()
      .describe('Channel the message arrived on (default: unknown)'),
    sender: z
      .string()
      .max(256)
      .optional()
      .describe('Sender identifier (phone number, email address, etc.)'),
    language: z
      .string()
      .max(16)
      .optional()
      .describe('Language hint (ISO code) or "auto" if unknown')
  }),
  async run({ args }) {
    if (!BRAID_INTERNAL_TOKEN) {
      return JSON.stringify({
        error:
          'BRAID_INTERNAL_TOKEN missing in services/braid/.env — cannot reach Etornie API',
        capability: 'triage_customer_message'
      })
    }

    const payload = {
      message_text: args.message_text,
      channel: args.channel ?? 'unknown',
      sender: args.sender ?? null,
      language: args.language ?? null
    }

    let response: Response
    try {
      response = await fetch(
        `${ETORNIE_API_BASE_URL}/braid/triage-message`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-Braid-Auth': BRAID_INTERNAL_TOKEN
          },
          body: JSON.stringify(payload)
        }
      )
    } catch (err) {
      return JSON.stringify({
        error: `etornie api unreachable at ${ETORNIE_API_BASE_URL}: ${
          err instanceof Error ? err.message : String(err)
        }`,
        capability: 'triage_customer_message'
      })
    }

    const text = await response.text()
    if (!response.ok) {
      return JSON.stringify({
        error: `etornie api ${response.status}: ${text || 'empty body'}`,
        capability: 'triage_customer_message'
      })
    }

    return text
  }
})

const { stop } = await run(agent)

console.log(
  `[braid] agent up — tunnel connected via agents-proxy.openserv.ai (port ${
    process.env.PORT ?? '7378'
  })`
)
console.log(
  '[braid] capabilities: ping, verify_x402_payment, verify_zk_file_ownership, triage_customer_message, route_office_response, score_document_completeness'
)
console.log('[braid] press ctrl+c to stop')

void stop
