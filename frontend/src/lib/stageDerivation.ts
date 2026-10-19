// Stage model (7 stages): Design, Build, Test, Review, Commit & PR, QA & UAT, Release & Docs.
// The backend (sdlc_orbit/state.py::STEP_TO_STAGE) stamps a `stage` on every turn and a `step`
// on pipeline_state; the map below must stay in sync with it.
import { AGENT_INITIALS, STAGE_AGENT_IDS, STAGE_NAMES } from '../constants'
import type { PipelineState, Session, StageStatus, Turn } from '../types'

const KNOWN_BASE_AGENT_IDS = Object.keys(AGENT_INITIALS)

export function baseAgentId(id: string | undefined | null): string {
  if (!id) return id ?? ''
  if (KNOWN_BASE_AGENT_IDS.includes(id)) return id
  const dash = id.lastIndexOf('-')
  if (dash > 0) {
    const candidate = id.slice(0, dash)
    if (KNOWN_BASE_AGENT_IDS.includes(candidate)) return candidate
  }
  return id
}

export function stageIndexFromState(pipelineState: PipelineState): number {
  const step = pipelineState.step
  const map: Record<string, number> = {
    design: 0,
    build: 1,
    test: 2,
    review: 3,
    commit: 4,
    qa_deploy: 5,
    qa_confirm: 5,
    uat: 5,
    pr_approval: 6,
    merge: 6,
    prod_preflight: 6,
    prod_deploy: 6,
    prod_confirm: 6,
    docs_preflight: 6,
    docs: 6,
    complete: 6,
  }
  return step && step in map ? map[step] : 0
}

export function stageStatuses(session: Session | null): StageStatus[] {
  const status = session ? session.status : 'idle'
  if (!session || status === null || status === undefined) {
    return STAGE_AGENT_IDS.map(() => 'idle')
  }
  const state = session.pipeline_state
  if (!state || !state.step) return STAGE_AGENT_IDS.map(() => 'idle')
  const current = stageIndexFromState(state)
  const activeAgents = state.active_agents || []
  const awaiting = status === 'awaiting_input' && activeAgents.length > 0
  return STAGE_AGENT_IDS.map((_, i) => {
    if (i < current) return 'done'
    if (i === current) {
      if (status === 'cancelled' || status === 'aborted') return 'cancelled'
      if (status === 'error') return 'failed'
      if (status === 'paused') return 'idle'
      if (status === 'complete') return 'done'
      if (awaiting) return 'awaiting'
      return 'running'
    }
    return 'idle'
  })
}

export interface HeaderStatus {
  s: StageStatus | 'idle'
  l: string
}

export function headerStatus(session: Session | null): HeaderStatus {
  if (!session || session.status === undefined) return { s: 'idle', l: 'No active session' }
  const state = session.pipeline_state
  const current = state?.step ? stageIndexFromState(state) : 0
  if (session.status === 'complete') return { s: 'done', l: 'Complete · all stages done' }
  if (session.status === 'cancelled' || session.status === 'aborted')
    return { s: 'idle', l: 'Cancelled · ' + (STAGE_NAMES[current] ?? '') }
  if (session.status === 'paused') return { s: 'idle', l: 'Paused · ' + (STAGE_NAMES[current] ?? '') }
  if (session.status === 'error') return { s: 'failed', l: 'Failed · ' + (STAGE_NAMES[current] ?? '') }
  if (session.status === 'awaiting_input') return { s: 'awaiting', l: 'Awaiting you · ' + (STAGE_NAMES[current] ?? '') }
  return { s: 'running', l: 'In progress · ' + (STAGE_NAMES[current] ?? '') }
}

export function turnStageIndex(turn: Turn): number {
  if (typeof turn.stage === 'number') return turn.stage
  const base = baseAgentId(turn.agent)
  for (let i = 0; i < STAGE_AGENT_IDS.length; i++) {
    if (STAGE_AGENT_IDS[i].includes(base)) return i
  }
  return 0
}

export function lastGateQuestionForStage(turns: Turn[], stageIndex: number): { question: string; agent: string } | null {
  const ids = STAGE_AGENT_IDS[stageIndex] || []
  for (let i = turns.length - 1; i >= 0; i--) {
    const t = turns[i]
    if (t.role !== 'agent_text') continue
    if (typeof t.stage === 'number') {
      if (t.stage !== stageIndex) continue
    } else if (!ids.includes(baseAgentId(t.agent)) && t.agent !== 'pipeline-orchestrator') {
      continue
    }
    return { question: t.text, agent: t.agent }
  }
  return null
}

export function whoForStage(session: Session, stageIndex: number): string | null {
  const state = session.pipeline_state
  const active = state?.active_agents || []
  if (active.length <= 1) return null
  const ids = STAGE_AGENT_IDS[stageIndex] || []
  for (const a of active) {
    if (ids.includes(baseAgentId(a))) return a
  }
  return active[0]
}
