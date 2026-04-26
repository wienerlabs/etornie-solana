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

const { stop } = await run(agent)

console.log(
  `[braid] agent up — tunnel connected via agents-proxy.openserv.ai (port ${
    process.env.PORT ?? '7378'
  })`
)
console.log('[braid] capabilities: ping, verify_x402_payment')
console.log('[braid] press ctrl+c to stop')

void stop
