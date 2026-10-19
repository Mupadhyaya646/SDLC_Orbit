-- SDLC_Orbit application schema (all statements idempotent; applied on every start).
--
-- These tables are PROJECTIONS for the dashboard plus the audit trail.
-- The source of truth for pipeline progress is the LangGraph checkpoint
-- (checkpoints, checkpoint_blobs, checkpoint_writes), created separately by
-- AsyncPostgresSaver.setup() at startup. thread_id == session_id.

CREATE TABLE IF NOT EXISTS pipeline_sessions (
    session_id      TEXT PRIMARY KEY,
    slug            TEXT NOT NULL,
    request         TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- in_progress | awaiting_input | complete | aborted | paused | error
    status          TEXT NOT NULL DEFAULT 'in_progress',
    current_agent   TEXT,
    -- {"step": ..., "active_agents": [...], "context": {...}} -- what the dashboard's stage rail reads
    pipeline_state  JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by      TEXT,
    error           TEXT
);

-- Transcript the dashboard streams over SSE.
--   role 'user'      the human's message (initial request or gate answer)
--   role 'assistant' an agent's turn output (may be a gate question or a final answer)
--   role 'activity'  tool-call progress; never shown as a gate question
CREATE TABLE IF NOT EXISTS agent_turns (
    id          BIGSERIAL PRIMARY KEY,
    session_id  TEXT NOT NULL REFERENCES pipeline_sessions(session_id) ON DELETE CASCADE,
    agent_name  TEXT NOT NULL,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    step        TEXT,
    stage       INTEGER,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS agent_turns_session_idx ON agent_turns (session_id, id);

CREATE TABLE IF NOT EXISTS handoff_payloads (
    id          BIGSERIAL PRIMARY KEY,
    session_id  TEXT NOT NULL REFERENCES pipeline_sessions(session_id) ON DELETE CASCADE,
    from_agent  TEXT NOT NULL,
    to_agent    TEXT NOT NULL,
    payload     JSONB NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS handoff_payloads_session_idx ON handoff_payloads (session_id, created_at);

-- Audit trail: proves a human, never an agent, answered every gate.
-- answered_by is stamped by the API/webhook layer from the verified identity,
-- never from agent output.
CREATE TABLE IF NOT EXISTS gate_log (
    id           BIGSERIAL PRIMARY KEY,
    session_id   TEXT NOT NULL REFERENCES pipeline_sessions(session_id) ON DELETE CASCADE,
    agent_name   TEXT NOT NULL,
    gate_name    TEXT NOT NULL,
    question     TEXT NOT NULL,
    answer       TEXT,
    answered_by  TEXT,
    answered_at  TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS gate_log_session_idx ON gate_log (session_id, id);
