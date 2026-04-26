/**
 * Audit wrapper for BRAID capabilities.
 *
 * Every capability registered through {@link addAuditedCapability} POSTs an
 * audit record to the Etornie API after each invocation, fire-and-forget. If
 * the API is down or the token is missing the capability still returns its
 * normal result — auditing is best-effort, never on the critical path.
 */

import type { Agent } from '@openserv-labs/sdk'
import type { z } from 'zod'

const ETORNIE_API_BASE_URL =
  process.env.ETORNIE_API_BASE_URL ?? 'http://localhost:8000'
const BRAID_INTERNAL_TOKEN = process.env.BRAID_INTERNAL_TOKEN ?? ''

interface ChatMessage {
  role?: string
  author?: string
  content?: string
  message?: string
}

interface ActionLike {
  workspace?: { id?: string }
  workspaceUpdateToken?: string
  workspaceId?: string
  threadId?: number
  me?: { id?: number; name?: string }
  messages?: ChatMessage[]
}

interface AuditRecord {
  workspace_id: string
  thread_id: number
  agent_id: number
  agent_name?: string
  capability_name: string
  args: unknown
  result: Record<string, unknown> | null
  error: string | null
  user_message: string | null
  started_at: string
  completed_at: string
  duration_ms: number
}

interface DecisionContext {
  workspace_id: string
  thread_id: number
  agent_id: number
  agent_name?: string
  user_message: string | null
}

async function postDecision(record: AuditRecord): Promise<void> {
  if (!BRAID_INTERNAL_TOKEN) return
  try {
    const res = await fetch(`${ETORNIE_API_BASE_URL}/braid/decisions`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Braid-Auth': BRAID_INTERNAL_TOKEN
      },
      body: JSON.stringify(record)
    })
    if (!res.ok) {
      const body = await res.text().catch(() => 'unreadable')
      console.warn(
        `[braid] audit log POST returned ${res.status}: ${body}`
      )
    }
  } catch (err) {
    console.warn(
      '[braid] audit log POST failed:',
      err instanceof Error ? err.message : String(err)
    )
  }
}

function extractContext(action: ActionLike | undefined): DecisionContext {
  const safeAction: ActionLike = action ?? {}
  const userMsg = safeAction.messages
    ?.slice()
    .reverse()
    .find(m => (m.role ?? m.author) === 'user')
  return {
    workspace_id:
      safeAction.workspace?.id ??
      safeAction.workspaceUpdateToken ??
      safeAction.workspaceId ??
      'unknown',
    thread_id: safeAction.threadId ?? 0,
    agent_id: safeAction.me?.id ?? 0,
    agent_name: safeAction.me?.name,
    user_message: userMsg?.content ?? userMsg?.message ?? null
  }
}

function safeParseResult(text: string): Record<string, unknown> {
  try {
    const parsed: unknown = JSON.parse(text)
    if (typeof parsed === 'object' && parsed !== null) {
      return parsed as Record<string, unknown>
    }
    return { raw: text }
  } catch {
    return { raw: text }
  }
}

// ── BRAID guardrail block injected into every capability response ──
// The reasoning runtime LLM reads this field directly and is instructed
// (via the agent's system prompt) to honor it absolutely. This is the
// strongest signal we can give a single-shot LLM about its boundaries
// short of post-processing the final response (which we cannot do — the
// runtime sends the LLM output to the user without us in the loop).

const REGISTERED_CAPABILITIES = new Set<string>()

function buildConstraintBlock(): Record<string, unknown> {
  return {
    available_capabilities_now: Array.from(REGISTERED_CAPABILITIES).sort(),
    you_must_not: [
      "claim to queue background work (e.g. 'I've queued it', 'queued the request')",
      "promise future notifications (e.g. 'I'll notify you when ready', 'I'll send you the result')",
      "promise to re-run capabilities later (e.g. 'I'll rescore automatically', 'will re-run')",
      "claim an escalation happened unless you literally just called requestHumanAssistance and it returned success in this same turn",
      "offer to perform actions outside available_capabilities_now (e.g. 'I can run a manual search', 'I can summon an attorney', 'I can prepare a draft for you')"
    ],
    if_user_asks_for_unsupported_action:
      "Reply with: 'I do not have a tool to do X. To proceed, an operator must Y manually. Send me a new message after that and I will continue.' Then STOP. Do not append future-tense self-promises.",
    after_your_reply_there_is_no_loop_back:
      "The orchestration runtime does not call you again on its own. You are a single-shot responder per turn. Anything you say will happen later WILL NOT happen unless the user explicitly triggers it."
  }
}

function injectConstraints(
  result: Record<string, unknown>
): Record<string, unknown> {
  return {
    ...result,
    _braid_constraints: buildConstraintBlock()
  }
}

interface AuditedRunnableCapability<S extends z.ZodTypeAny> {
  name: string
  description: string
  inputSchema: S
  outputSchema?: never
  run: (
    this: Agent,
    params: { args: z.infer<S>; action: unknown },
    messages: unknown[]
  ) => string | Promise<string>
}

/**
 * Register a capability whose every invocation is logged to the Etornie
 * audit trail (`POST /braid/decisions`). Logging is fire-and-forget;
 * capability response time is not affected by audit DB latency.
 */
export function addAuditedCapability<S extends z.ZodTypeAny>(
  agent: Agent,
  config: AuditedRunnableCapability<S>
): void {
  REGISTERED_CAPABILITIES.add(config.name)
  const original = config.run

  const wrapped = {
    name: config.name,
    description: config.description,
    inputSchema: config.inputSchema,
    async run(
      this: Agent,
      params: { args: z.infer<S>; action: unknown },
      messages: unknown[]
    ): Promise<string> {
      const startedAt = Date.now()
      const ctx = extractContext(params.action as ActionLike | undefined)

      let resultText: string
      try {
        resultText = await original.call(this, params, messages)
      } catch (e) {
        const errorMsg = e instanceof Error ? e.message : String(e)
        const completedAt = Date.now()
        void postDecision({
          ...ctx,
          capability_name: config.name,
          args: params.args,
          result: null,
          error: errorMsg,
          started_at: new Date(startedAt).toISOString(),
          completed_at: new Date(completedAt).toISOString(),
          duration_ms: completedAt - startedAt
        })
        throw e
      }

      const completedAt = Date.now()
      const parsedResult = safeParseResult(resultText)
      const enrichedResult = injectConstraints(parsedResult)
      void postDecision({
        ...ctx,
        capability_name: config.name,
        args: params.args,
        result: enrichedResult,
        error: null,
        started_at: new Date(startedAt).toISOString(),
        completed_at: new Date(completedAt).toISOString(),
        duration_ms: completedAt - startedAt
      })

      // Hand the enriched payload (with _braid_constraints) back to the
      // BRAID runtime LLM so it sees the boundary block directly in the
      // tool-call response. The system prompt instructs it to honor this.
      return JSON.stringify(enrichedResult)
    }
  }

  // The SDK's addCapability has a deeply-discriminated CapabilityConfig
  // generic over the agent's MCP-server tag. Our wrapped object satisfies
  // the runnable shape at runtime; the cast bridges the structural gap.
  agent.addCapability(
    wrapped as unknown as Parameters<Agent['addCapability']>[0]
  )
}
