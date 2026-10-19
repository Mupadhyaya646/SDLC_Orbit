"""Async Postgres access for the *application* tables (UI projections + audit).

Source of truth for pipeline progress is the LangGraph checkpoint (tables
created by ``AsyncPostgresSaver.setup()``). The tables here are projections for
the dashboard (``pipeline_sessions``, ``agent_turns``) plus the audit trail that
proves a human answered every gate (``gate_log``) and the agent-to-agent
``handoff_payloads``.

One psycopg ``AsyncConnectionPool`` is shared with the checkpointer; it MUST be
opened with autocommit=True, prepare_threshold=0 and dict_row (LangGraph's
Postgres saver requirement), which ``make_pool`` guarantees.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from .config import database_dsn

logger = logging.getLogger("sdlc_orbit.db")

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"

_pool: AsyncConnectionPool | None = None


class SessionBusyError(RuntimeError):
    """A run is already in progress for this session."""


def make_pool(dsn: str | None = None, max_size: int = 10) -> AsyncConnectionPool:
    return AsyncConnectionPool(
        conninfo=dsn or database_dsn(),
        max_size=max_size,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        open=False,
    )


async def init_pool(max_size: int = 10) -> AsyncConnectionPool:
    global _pool
    if _pool is None:
        _pool = make_pool(max_size=max_size)
        await _pool.open(wait=True, timeout=30)
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def pool() -> AsyncConnectionPool:
    if _pool is None:
        raise RuntimeError("database pool not initialised; call init_pool() first")
    return _pool


async def run_migrations() -> None:
    """Apply every migrations/*.sql in filename order (all idempotent)."""
    async with pool().connection() as conn:
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            await conn.execute(path.read_text(encoding="utf-8"))
            logger.info("applied migration %s", path.name)


@asynccontextmanager
async def session_lock(session_id: str) -> AsyncIterator[None]:
    """Postgres advisory lock scoped to one session, held for one graph run.

    Fails fast (``pg_try_advisory_lock``) rather than queueing: a queued second
    request would resume against state picked up before the first run's writes
    landed. Uses a dedicated connection because advisory locks belong to the
    connection that took them. A hash collision between two session ids can only
    cause one to briefly, wrongly report "busy" -- never corrupt state.
    """
    conn = await psycopg.AsyncConnection.connect(database_dsn(), autocommit=True)
    try:
        cur = await conn.execute("SELECT pg_try_advisory_lock(hashtext(%s)) AS got", (session_id,))
        row = await cur.fetchone()
        if not row or not row[0]:
            raise SessionBusyError(f"a run is already in progress for session {session_id!r}")
        try:
            yield
        finally:
            await conn.execute("SELECT pg_advisory_unlock(hashtext(%s))", (session_id,))
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


async def _one(sql: str, params: tuple = ()) -> dict[str, Any] | None:
    async with pool().connection() as conn:
        cur = await conn.execute(sql, params)
        return await cur.fetchone()


async def _all(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    async with pool().connection() as conn:
        cur = await conn.execute(sql, params)
        return await cur.fetchall()


async def _exec(sql: str, params: tuple = ()) -> None:
    async with pool().connection() as conn:
        await conn.execute(sql, params)


# ---------------------------------------------------------------------------
# sessions
# ---------------------------------------------------------------------------


async def create_session(session_id: str, slug: str, request: str, created_by: str | None, current_agent: str | None) -> None:
    await _exec(
        "INSERT INTO pipeline_sessions (session_id, slug, request, status, current_agent, created_by) "
        "VALUES (%s, %s, %s, 'in_progress', %s, %s)",
        (session_id, slug, request, current_agent, created_by),
    )


async def get_session(session_id: str) -> dict[str, Any] | None:
    return await _one(
        "SELECT session_id, slug, request, created_at, updated_at, status, current_agent, pipeline_state, created_by, error "
        "FROM pipeline_sessions WHERE session_id = %s",
        (session_id,),
    )


async def set_status(session_id: str, status: str, current_agent: str | None = None, error: str | None = None) -> None:
    await _exec(
        "UPDATE pipeline_sessions SET status = %s, current_agent = %s, error = %s, updated_at = now() "
        "WHERE session_id = %s",
        (status, current_agent, error, session_id),
    )


async def in_progress_session_ids() -> list[str]:
    rows = await _all("SELECT session_id FROM pipeline_sessions WHERE status = 'in_progress'")
    return [r["session_id"] for r in rows]


async def ping() -> None:
    await _one("SELECT 1 AS ok")


async def set_ui_state(session_id: str, state: dict[str, Any]) -> None:
    await _exec(
        "UPDATE pipeline_sessions SET pipeline_state = %s, updated_at = now() WHERE session_id = %s",
        (Jsonb(state), session_id),
    )


# ---------------------------------------------------------------------------
# turns (the transcript the dashboard streams)
# ---------------------------------------------------------------------------


async def append_turn(
    session_id: str,
    agent_name: str,
    role: str,
    content: str,
    step: str | None = None,
    stage: int | None = None,
) -> dict[str, Any]:
    """role: 'user' | 'assistant' | 'activity' (tool progress; never a gate question)."""
    row = await _one(
        "INSERT INTO agent_turns (session_id, agent_name, role, content, step, stage) "
        "VALUES (%s, %s, %s, %s, %s, %s) "
        "RETURNING id, session_id, agent_name, role, content, step, stage, created_at",
        (session_id, agent_name, role, content, step, stage),
    )
    assert row is not None
    return row


async def list_turns(session_id: str, after_id: int = 0, include_activity: bool = True) -> list[dict[str, Any]]:
    sql = (
        "SELECT id, session_id, agent_name, role, content, step, stage, created_at "
        "FROM agent_turns WHERE session_id = %s AND id > %s "
    )
    if not include_activity:
        sql += "AND role <> 'activity' "
    sql += "ORDER BY id"
    return await _all(sql, (session_id, after_id))


# ---------------------------------------------------------------------------
# gates (audit trail)
# ---------------------------------------------------------------------------


async def record_gate(session_id: str, agent_name: str, gate_name: str, question: str) -> int:
    row = await _one(
        "INSERT INTO gate_log (session_id, agent_name, gate_name, question) VALUES (%s, %s, %s, %s) RETURNING id",
        (session_id, agent_name, gate_name, question),
    )
    assert row is not None
    return int(row["id"])


async def open_gate(session_id: str) -> dict[str, Any] | None:
    """The newest unanswered gate for this session, if any."""
    return await _one(
        "SELECT id, session_id, agent_name, gate_name, question FROM gate_log "
        "WHERE session_id = %s AND answer IS NULL ORDER BY id DESC LIMIT 1",
        (session_id,),
    )


async def answer_gate(session_id: str, gate_id: int, answer: str, answered_by: str) -> bool:
    """Stamp the answer + verified identity on a still-open gate. False if already answered."""
    row = await _one(
        "UPDATE gate_log SET answer = %s, answered_by = %s, answered_at = now() "
        "WHERE id = %s AND session_id = %s AND answer IS NULL RETURNING id",
        (answer, answered_by, gate_id, session_id),
    )
    return row is not None


async def list_gates(session_id: str) -> list[dict[str, Any]]:
    return await _all(
        "SELECT id, session_id, agent_name, gate_name, question, answer, answered_by, answered_at, created_at "
        "FROM gate_log WHERE session_id = %s ORDER BY id",
        (session_id,),
    )


# ---------------------------------------------------------------------------
# handoffs
# ---------------------------------------------------------------------------


async def record_handoff(session_id: str, from_agent: str, to_agent: str, payload: dict[str, Any]) -> None:
    await _exec(
        "INSERT INTO handoff_payloads (session_id, from_agent, to_agent, payload) VALUES (%s, %s, %s, %s)",
        (session_id, from_agent, to_agent, Jsonb(payload)),
    )
