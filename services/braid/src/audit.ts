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
      void postDecision({
        ...ctx,
        capability_name: config.name,
        args: params.args,
        result: safeParseResult(resultText),
        error: null,
        started_at: new Date(startedAt).toISOString(),
        completed_at: new Date(completedAt).toISOString(),
        duration_ms: completedAt - startedAt
      })

      return resultText
    }
  }

  // The SDK's addCapability has a deeply-discriminated CapabilityConfig
  // generic over the agent's MCP-server tag. Our wrapped object satisfies
  // the runnable shape at runtime; the cast bridges the structural gap.
  agent.addCapability(
    wrapped as unknown as Parameters<Agent['addCapability']>[0]
  )
}
