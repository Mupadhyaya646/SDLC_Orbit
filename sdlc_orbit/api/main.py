"""SDLC_Orbit API -- a thin HTTP layer over the LangGraph runtime (Lane 2).

No agent logic lives here. It starts and resumes graph runs, bridges the run to
the browser (SSE), and -- crucially -- stamps every gate answer with a verified
human identity before the graph is resumed.

Contract kept identical to the Cortex-era backend so the dashboard is unchanged:

  POST /api/sessions                 start a run           -> {id, agent}
  GET  /api/sessions/{id}            status / poll
  GET  /api/sessions/{id}/events     SSE (replay + live tail)
  POST /api/sessions/{id}/reply      answer the open gate  -> {ok}
  GET  /api/sessions/{id}/agents     roster + live status
  GET  /api/sessions/{id}/log        every turn / decision
  GET  /api/sessions/{id}/journal    decision audit trail
Added:
  POST /api/sessions/{id}/retry      re-run from the last checkpoint after status 'error'
  GET  /healthz, /readyz

Runs execute as background asyncio tasks, so POST /api/sessions and /reply return
immediately and progress streams over SSE (the Cortex-era API blocked the request
for the whole agent turn).
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command
from pydantic import BaseModel

from .. import db
from ..agents import AGENTS
from ..config import cortex_settings, llm_settings, runtime_settings
from ..cortex import CortexClient
from ..graph import Deps, build_graph
from ..llm import get_chat_model
from ..mcp_tools import get_registry
from . import view
from .identity import IdentityError, resolve_identity
from .sse import SseEvent, heartbeat_frame, retry_frame

logger = logging.getLogger("sdlc_orbit.api")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
FIRST_AGENT = AGENTS["design"].agent_id


# ---------------------------------------------------------------------------
# run management
# ---------------------------------------------------------------------------


class RunManager:
    """Owns background graph runs (one at a time per session, enforced by an
    advisory lock so it also holds across pods/workers)."""

    def __init__(self, graph: Any, recursion_limit: int) -> None:
        self.graph = graph
        self._recursion_limit = recursion_limit
        self._tasks: set[asyncio.Task] = set()

    def config(self, session_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": session_id}, "recursion_limit": self._recursion_limit}

    def launch(self, session_id: str, payload: Any) -> None:
        task = asyncio.create_task(self._run(session_id, payload), name=f"run-{session_id}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run(self, session_id: str, payload: Any) -> None:
        try:
            async with db.session_lock(session_id):
                await self.graph.ainvoke(payload, self.config(session_id))
        except db.SessionBusyError:
            logger.warning("run for %s skipped: another run holds the lock", session_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - surface to the dashboard, keep the checkpoint
            logger.exception("run failed for session %s", session_id)
            await db.set_status(session_id, "error", error=f"{type(exc).__name__}: {exc}"[:2000])

    async def open_interrupt(self, session_id: str) -> dict[str, Any] | None:
        """Payload of the pending gate interrupt, or None when the graph is not paused at one."""
        snapshot = await self.graph.aget_state(self.config(session_id))
        for task in snapshot.tasks:
            for itr in task.interrupts:
                return itr.value
        return None

    async def shutdown(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)


async def _sweep_orphaned_runs() -> int:
    """Mark sessions left 'in_progress' by a crashed/restarted pod as 'error'.

    A session whose advisory lock can be taken has no live run anywhere (another
    pod's live run would hold it), so it is safe to mark and to offer /retry.
    """
    swept = 0
    for session_id in await db.in_progress_session_ids():
        try:
            async with db.session_lock(session_id):
                await db.set_status(session_id, "error", error="run interrupted by a service restart; use retry to continue")
                swept += 1
        except db.SessionBusyError:
            continue
    return swept


@asynccontextmanager
async def lifespan(app: FastAPI):
    rt = runtime_settings()
    cortex_cfg = cortex_settings()
    if cortex_cfg is None:
        llm_settings()  # fail fast on a missing ANTHROPIC_API_KEY / LLM_MODEL
    await db.init_pool(max_size=rt.db_pool_max)
    await db.run_migrations()
    saver = AsyncPostgresSaver(db.pool())
    await saver.setup()
    registry = get_registry()
    deps = Deps(
        llm=get_chat_model,
        tools=registry.tools_for,
        store=db,
        max_rework_loops=rt.max_rework_loops,
        require_design_confirmation=os.getenv("ORBIT_REQUIRE_DESIGN_CONFIRMATION", "true").lower() in ("1", "true", "yes", "on"),
        cortex=CortexClient(cortex_cfg) if cortex_cfg else None,
    )
    graph = build_graph(deps).compile(checkpointer=saver)
    app.state.runs = RunManager(graph, rt.recursion_limit)
    app.state.rt = rt
    swept = await _sweep_orphaned_runs()
    logger.info("SDLC_Orbit ready (orphaned runs marked for retry: %d)", swept)
    try:
        yield
    finally:
        await app.state.runs.shutdown()
        await db.close_pool()


app = FastAPI(title="SDLC_Orbit API", lifespan=lifespan)


# ---------------------------------------------------------------------------
# models / helpers
# ---------------------------------------------------------------------------


class CreateSessionRequest(BaseModel):
    text: str


class ReplyRequest(BaseModel):
    text: str
    answered_by: str | None = None  # only used when no verified identity header is present
    agent: str | None = None  # accepted for dashboard compatibility; only one gate is ever open


_SLUG_MAX = 60


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", text.strip().lower()).strip("-")
    return (slug or "session")[:_SLUG_MAX]


def _identity(request: Request, body_answered_by: str | None) -> str:
    rt = request.app.state.rt
    try:
        return resolve_identity(
            request.headers,
            body_answered_by,
            mode=rt.identity_mode,
            configured_header=rt.identity_header,
            strict=rt.identity_strict,
        )
    except IdentityError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


async def _require_session(session_id: str) -> dict[str, Any]:
    session = await db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="unknown session")
    return session


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------


@app.get("/healthz")
async def healthz() -> dict[str, bool]:
    """Liveness only: no DB / LLM / MCP dependency."""
    return {"ok": True}


@app.get("/readyz")
async def readyz(request: Request) -> dict[str, Any]:
    report: dict[str, Any] = {}
    try:
        await db.ping()
        report["database"] = "ok"
    except Exception as exc:  # noqa: BLE001
        report["database"] = f"error: {exc}"
    report["mcp"] = await get_registry().health()
    report["ok"] = report["database"] == "ok"
    return report


@app.post("/api/sessions")
async def create_session(body: CreateSessionRequest, request: Request) -> dict[str, str]:
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="text required")
    session_id = str(uuid.uuid4())
    created_by = _identity(request, None)
    await db.create_session(session_id, _slugify(text), text, created_by, FIRST_AGENT)
    request.app.state.runs.launch(session_id, {"session_id": session_id, "request": text})
    return {"id": session_id, "agent": FIRST_AGENT}


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str) -> dict[str, Any]:
    return await _require_session(session_id)


@app.post("/api/sessions/{session_id}/reply")
async def reply_to_session(session_id: str, body: ReplyRequest, request: Request) -> dict[str, bool]:
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="text required")
    session = await _require_session(session_id)
    if session["status"] != "awaiting_input":
        raise HTTPException(status_code=409, detail=f"session is not awaiting input (status: {session['status']})")

    runs: RunManager = request.app.state.runs
    interrupt_payload = await runs.open_interrupt(session_id)
    gate = await db.open_gate(session_id)
    if interrupt_payload is None or gate is None:
        raise HTTPException(status_code=409, detail="no gate is open yet; retry in a moment")
    if interrupt_payload.get("gate_id") != gate["id"]:
        raise HTTPException(status_code=409, detail="the open gate changed; reload and answer the current one")

    identity = _identity(request, body.answered_by)
    # Atomic: exactly one concurrent reply can win.
    if not await db.answer_gate(session_id, gate["id"], text, identity):
        raise HTTPException(status_code=409, detail="this gate was already answered")

    step = interrupt_payload.get("step")
    await db.append_turn(session_id, gate["agent_name"], "user", text, step, view.stage_for_step(step))
    await db.set_status(session_id, "in_progress", current_agent=gate["agent_name"])
    runs.launch(
        session_id,
        Command(resume={"text": text, "answered_by": identity, "gate_id": gate["id"], "source": "api"}),
    )
    return {"ok": True}


@app.post("/api/sessions/{session_id}/retry")
async def retry_session(session_id: str, request: Request) -> dict[str, bool]:
    session = await _require_session(session_id)
    if session["status"] != "error":
        raise HTTPException(status_code=409, detail=f"only a session in 'error' can be retried (status: {session['status']})")
    await db.set_status(session_id, "in_progress", current_agent=session.get("current_agent"))
    request.app.state.runs.launch(session_id, None)  # None => continue from the last checkpoint
    return {"ok": True}


@app.get("/api/sessions/{session_id}/events")
async def stream_events(session_id: str, request: Request) -> StreamingResponse:
    await _require_session(session_id)
    rt = request.app.state.rt
    kinds = {"user": "user", "assistant": "agent_text", "activity": "activity"}

    async def event_stream():
        yield retry_frame(rt.sse_retry_ms)
        last_id, seq = 0, 0
        last_heartbeat = time.monotonic()
        while True:
            if await request.is_disconnected():
                break
            for row in await db.list_turns(session_id, after_id=last_id):
                last_id = row["id"]
                seq += 1
                yield SseEvent(
                    seq=seq,
                    kind=kinds.get(row["role"], "agent_text"),
                    data={
                        "agent": row["agent_name"],
                        "text": row["content"],
                        "created_at": row["created_at"].isoformat(),
                        "step": row["step"],
                        "stage": row["stage"],
                    },
                ).frame()
            if time.monotonic() - last_heartbeat >= rt.sse_heartbeat_seconds:
                yield heartbeat_frame()
                last_heartbeat = time.monotonic()
            await asyncio.sleep(rt.sse_poll_seconds)

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers={"Cache-Control": "no-store", "Connection": "keep-alive"})


@app.get("/api/sessions/{session_id}/agents")
async def get_agents(session_id: str) -> dict[str, Any]:
    session = await _require_session(session_id)
    statuses = view.agent_statuses(session["status"], session.get("pipeline_state") or {})
    last_activity: dict[str, str] = {}
    for t in await db.list_turns(session_id, include_activity=False):
        last_activity[t["agent_name"]] = t["created_at"].isoformat()
    return {
        "agents": [
            {**a, "status": statuses.get(a["id"], "idle"), "last_activity": last_activity.get(a["id"])} for a in view.AGENT_ROSTER
        ]
    }


@app.get("/api/sessions/{session_id}/log")
async def get_log(session_id: str) -> dict[str, Any]:
    await _require_session(session_id)
    rows = view.log_rows(await db.list_turns(session_id), await db.list_gates(session_id))
    for row in rows:
        if row["time"] is not None:
            row["time"] = row["time"].isoformat()
    return {"entries": rows}


@app.get("/api/sessions/{session_id}/journal")
async def get_journal(session_id: str) -> dict[str, Any]:
    await _require_session(session_id)
    rows = view.journal_rows(await db.list_gates(session_id))
    for row in rows:
        if row["answered_at"] is not None:
            row["answered_at"] = row["answered_at"].isoformat()
    return {"entries": rows}


# ---------------------------------------------------------------------------
# static dashboard -- mounted LAST so it never shadows /api/* or /healthz
# ---------------------------------------------------------------------------

if (STATIC_DIR / "index.html").is_file():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
else:

    @app.get("/", response_class=HTMLResponse)
    async def ui_not_built() -> str:
        return (
            "<h1>SDLC_Orbit API is running</h1><p>The dashboard has not been built into this image. "
            "Build <code>frontend/</code> (see README) into <code>sdlc_orbit/static/</code>.</p>"
        )
