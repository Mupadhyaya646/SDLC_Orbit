"""One agent *turn*: call the model, run any tool calls, repeat until the model
answers without a tool call.

That final tool-less message is exactly what the unmodified agent prompts call
"ending your turn" -- either a finished result or a gate for the human. This
module never decides which; ``graph.py`` inspects the returned text.

Deliberately a plain loop (not a prebuilt ReAct helper): it gives exact control
over the "no tool call == end of turn" contract that gate detection relies on,
keeps the tool-call budget per turn explicit, and avoids depending on a
prebuilt-agent API that changes between LangChain releases.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Awaitable, Callable

logger = logging.getLogger("sdlc_orbit.runtime")

ActivityFn = Callable[[str], Awaitable[None]]

_EMPTY_NUDGE = "(Your previous response was empty. Respond to the instructions above.)"
_MAX_ARG_PREVIEW = 160
_MAX_RESULT_PREVIEW = 160


class AgentIterationLimit(RuntimeError):
    """The model kept calling tools past the per-turn budget.

    Carries the partial thread so a human-approved retry can continue from it.
    """

    def __init__(self, limit: int, thread: list[Any]) -> None:
        super().__init__(f"tool-call budget of {limit} model calls exhausted within one turn")
        self.limit = limit
        self.thread = thread


def message_text(msg: Any) -> str:
    """Plain text of a LangChain message (string content or a list of content blocks)."""
    content = getattr(msg, "content", msg)
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content or []:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")))
    return "".join(parts)


def _preview(value: Any, limit: int) -> str:
    try:
        text = value if isinstance(value, str) else json.dumps(value, default=str)
    except Exception:  # noqa: BLE001
        text = str(value)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "\u2026"


async def _run_tool(tool_by_name: dict[str, Any], call: dict[str, Any], on_activity: ActivityFn | None):
    from langchain_core.messages import ToolMessage

    name = call.get("name", "")
    call_id = call.get("id") or ""
    started = time.monotonic()
    tool = tool_by_name.get(name)
    if tool is None:
        # The model asked for a tool it was never given (least privilege). Tell it,
        # so it can adapt, rather than crashing the run.
        msg = f"Error: tool {name!r} is not available to this agent. Available tools: {sorted(tool_by_name) or 'none'}."
        if on_activity:
            await on_activity(f"\u26a0\ufe0f {name}: not an allowed tool")
        return ToolMessage(content=msg, tool_call_id=call_id, name=name, status="error")

    if on_activity:
        await on_activity(f"\U0001f527 {name}({_preview(call.get('args', {}), _MAX_ARG_PREVIEW)})")
    try:
        result = await tool.ainvoke(call)
    except Exception as exc:  # noqa: BLE001 - tool failures are information for the agent
        logger.warning("tool %s failed: %s", name, exc)
        if on_activity:
            await on_activity(f"\u274c {name} failed after {time.monotonic() - started:.1f}s: {_preview(str(exc), _MAX_RESULT_PREVIEW)}")
        return ToolMessage(
            content=f"Error calling {name}: {type(exc).__name__}: {exc}",
            tool_call_id=call_id,
            name=name,
            status="error",
        )

    if not isinstance(result, ToolMessage):
        result = ToolMessage(content=result if isinstance(result, str) else str(result), tool_call_id=call_id, name=name)
    if on_activity:
        await on_activity(f"\u2705 {name} ({time.monotonic() - started:.1f}s): {_preview(message_text(result), _MAX_RESULT_PREVIEW)}")
    return result


async def run_turn(
    *,
    llm: Any,
    tools: list[Any],
    system_prompt: str,
    thread: list[Any],
    user_text: str | None,
    max_iterations: int,
    on_activity: ActivityFn | None = None,
) -> tuple[list[Any], str]:
    """Run one turn. Returns ``(updated_thread, final_text)``.

    ``thread`` is this agent's own conversation so far (the equivalent of one
    Cortex session per agent); ``user_text`` is appended as a new human message
    unless ``None`` (continue a thread as-is).
    """
    from langchain_core.messages import HumanMessage, SystemMessage

    messages: list[Any] = list(thread)
    if user_text is not None:
        messages.append(HumanMessage(content=user_text))

    model = llm.bind_tools(tools) if tools else llm
    tool_by_name = {t.name: t for t in tools}
    nudged = False

    for _ in range(max_iterations):
        ai = await model.ainvoke([SystemMessage(content=system_prompt), *messages])
        messages.append(ai)

        calls = list(getattr(ai, "tool_calls", None) or [])
        if not calls:
            text = message_text(ai)
            if not text.strip() and not nudged:
                # Rare: a model returns nothing. One automatic nudge, mirroring the
                # Cortex-era "one automatic retry before bothering the human".
                nudged = True
                messages.append(HumanMessage(content=_EMPTY_NUDGE))
                continue
            return messages, text

        # Sequential, in order: the original agent chains ran with parallel_tool_calls=false.
        for call in calls:
            messages.append(await _run_tool(tool_by_name, call, on_activity))

    raise AgentIterationLimit(max_iterations, messages)
