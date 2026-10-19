export type SessionStatus =
  | 'idle'
  | 'in_progress'
  | 'awaiting_input'
  | 'complete'
  | 'aborted'
  | 'cancelled'
  | 'paused'
  | 'error'

export interface PipelineContext {
  has_admin?: boolean
  admin_done?: boolean
  has_dev?: boolean
  dev_done?: boolean
  testing_done?: boolean
  [key: string]: unknown
}

export interface PipelineState {
  step: string | null
  active_agents: string[]
  context: PipelineContext
}

export interface Session {
  session_id: string
  slug: string
  created_at: string
  status: SessionStatus
  current_agent: string | null
  pipeline_state: PipelineState | null
}

export interface CreateSessionResponse {
  id: string
  agent: string
}

export type AgentId = string

export type AgentRuntimeStatus = 'idle' | 'running' | 'awaiting' | 'done' | 'failed'

export interface AgentStatus {
  id: AgentId
  initials: string
  short: string
  role: string
  stages: number[]
  status: AgentRuntimeStatus
  last_activity: string | null
}

export interface AgentsResponse {
  agents: AgentStatus[]
}

export type LogEntryKind = 'turn' | 'decision'

export interface LogEntry {
  n: number
  time: string | null
  agent: string
  kind: LogEntryKind
  ok: boolean
  summary: string
  raw: Record<string, unknown>
}

export interface LogResponse {
  entries: LogEntry[]
}

export interface JournalEntry {
  id: string
  agent: string
  question: string
  answer: string | null
  answered_by: string | null
  answered_at: string | null
  pending: boolean
}

export interface JournalResponse {
  entries: JournalEntry[]
}

// "user" and "agent_text" are transcript turns; "activity" is tool-call progress and
// is deliberately not rendered as a turn (it must never become a gate question).
export type SSEEventKind = 'user' | 'agent_text' | 'activity'

export interface SSEEventData {
  agent: string
  text: string
  created_at: string
  step?: string | null
  // Stage index stamped by the backend; preferred over agent-based inference
  // because one agent (devops) works in more than one stage.
  stage?: number | null
}

export interface SSEEvent {
  seq: number
  kind: SSEEventKind
  data: SSEEventData
}

export interface Turn {
  agent: string
  text: string
  created_at: string
  role: 'user' | 'agent_text'
  stage?: number | null
}

export interface CreateSessionRequest {
  text: string
  agent?: string
}

export interface ReplyRequest {
  text: string
  answered_by?: string
  agent?: string
}

export type StageStatus = 'done' | 'awaiting' | 'running' | 'idle' | 'failed' | 'cancelled'

export type ConnectionStatus = 'connected' | 'reconnecting'
