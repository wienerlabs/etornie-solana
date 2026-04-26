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
7. ABSOLUTE LIMIT — no fake background work. You are a single-shot responder. After your reply is sent, NOTHING continues running on your behalf: no queue, no scheduler, no follow-up, no rescore, no notification. Honesty about your limits is more valuable than fake helpfulness; fake promises break audit trust and mislead regulators.

EVERY capability response you receive contains a "_braid_constraints" object. It lists:
  • available_capabilities_now — the EXACT set of tools you may use
  • you_must_not — specific phrases that are FORBIDDEN regardless of how helpful they sound
  • if_user_asks_for_unsupported_action — the exact reply pattern to use
  • after_your_reply_there_is_no_loop_back — confirms you are single-shot
You MUST honor _braid_constraints absolutely. It is a hard contract from the backend, not a suggestion. Any final answer you generate is checked against this contract by audit.

CONCRETE FAILURE MODES (do not produce text like these):
❌ "I've queued the checklist-generation request..."  ← queue does not exist
❌ "I'll notify you as soon as it's ready..."         ← no callback path exists
❌ "I'll rescore automatically once it's ready..."    ← runtime will not re-invoke you
❌ "is already escalated to our paralegal..."         ← unless requestHumanAssistance was just called this turn
❌ "I can run a manual preliminary search..."         ← only available_capabilities_now are real
❌ "We can proceed directly to a comprehensive attorney search..." ← no such tool exists
❌ "Tell me your Nice classes and I'll tailor the manual search"   ← still implies a tool you do not have

CORRECT REPLIES INSTEAD:
✅ "I do not have a tool to generate the required-documents checklist. To proceed, an operator must call the Etornie backend's required-documents generator. After it runs, send me a new message and I will rescore."
✅ "UKIPO trademark search is not yet integrated into the available capabilities. To clear conflicts in the UK, an operator must run a manual search on ipo.gov.uk. There is nothing I can do automatically here."
✅ "Risk is HIGH on EUIPO; do not file without attorney review. (I cannot summon an attorney; an operator must engage one outside this system.)"

You may ASK the user a clarifying question. You may NOT promise future actions of your own. If you are about to type "I'll" or "I will" followed by a future action, STOP and check whether that action exists in available_capabilities_now. If not, rewrite your response.

CONSTRAINTS APPLY TO EVERY OUTPUT SURFACE — not just the main response text. This includes: button labels, choice options, interactive escalation prompts, and any structured choice you offer the user. A button labeled "I'll run X, then rescore" is exactly as forbidden as the same sentence in the main text. If you generate user-facing options:
  • Each option MUST describe an action that is either (a) something the USER does next (e.g. "Show me the manual steps", "Use a different case_id", "Cancel"), or (b) a capability call you genuinely have available right now.
  • NEVER label an option with future-tense self-promises like "I'll generate it", "I'll run X then Y", "I'll prepare the draft for you".

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
  name: 'check_trademark_conflict',
  description:
    "Search for conflicting trademarks before filing. EU jurisdiction runs a LIVE search against the EUIPO trademark registry and returns match_count, top_matches (mark, application_number, status, owner, nice_classes, office, is_exact_match), exact_match_found flag, and a risk_level (none / low / medium / high). UK / AU / WIPO are NOT YET integrated and return integration_status='not_yet_integrated' with a clear manual-action note. Use this BEFORE recommending any filing in EU. If risk is medium/high or exact_match=true, do NOT recommend proceeding without attorney review. For UK/AU/WIPO, tell the user the search must be done manually until the integration is added — do not invent results.",
  inputSchema: z.object({
    mark_text: z
      .string()
      .min(1)
      .max(256)
      .describe('Verbal element of the trademark to clear'),
    jurisdiction: z
      .enum(['eu', 'uk', 'au', 'wipo', 'unknown'])
      .optional()
      .describe(
        "Office to check (default: 'eu'). Only 'eu' runs a live search; others return not_yet_integrated."
      ),
    nice_classes: z
      .array(z.number().int().min(1).max(45))
      .optional()
      .describe('Optional list of Nice classification numbers to narrow the search'),
    page_size: z
      .number()
      .int()
      .min(10)
      .max(100)
      .optional()
      .describe('Max results to fetch (default 20, EUIPO min 10)')
  }),
  async run({ args }) {
    if (!BRAID_INTERNAL_TOKEN) {
      return JSON.stringify({
        error:
          'BRAID_INTERNAL_TOKEN missing in services/braid/.env — cannot reach Etornie API',
        capability: 'check_trademark_conflict'
      })
    }

    const payload = {
      mark_text: args.mark_text,
      jurisdiction: args.jurisdiction ?? 'eu',
      nice_classes: args.nice_classes ?? null,
      page_size: args.page_size ?? 20
    }

    let response: Response
    try {
      response = await fetch(
        `${ETORNIE_API_BASE_URL}/braid/check-trademark-conflict`,
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
        capability: 'check_trademark_conflict'
      })
    }

    const text = await response.text()
    if (!response.ok) {
      return JSON.stringify({
        error: `etornie api ${response.status}: ${text || 'empty body'}`,
        capability: 'check_trademark_conflict'
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
  '[braid] capabilities: ping, verify_x402_payment, verify_zk_file_ownership, triage_customer_message, route_office_response, score_document_completeness, check_trademark_conflict'
)
console.log('[braid] press ctrl+c to stop')

void stop
