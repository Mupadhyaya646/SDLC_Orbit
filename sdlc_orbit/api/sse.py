"""SSE framing: ``id: N\ndata: {...}\n\n`` frames, numbered per connection and
replayed deterministically from the durable ``agent_turns`` log, so a client that
reconnects and de-duplicates by ``seq`` sees a consistent stream.

Event ``kind`` values:
  - "user"       the human's own message (initial request or gate answer)
  - "agent_text" an agent's turn output (may be a gate question or a final answer)
  - "activity"   tool-call progress; ignored by the current dashboard, safe to ignore
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass
class SseEvent:
    seq: int
    kind: str
    data: dict[str, Any]

    def frame(self) -> str:
        payload = {"seq": self.seq, "kind": self.kind, "data": self.data}
        return f"id: {self.seq}\ndata: {json.dumps(payload)}\n\n"


def heartbeat_frame() -> str:
    return ": hb\n\n"


def retry_frame(delay_ms: int) -> str:
    """EventSource's own reconnect-delay hint. Without this, the browser's
    default reconnect delay is near-instant, which (observed live on
    the deployed dashboard) hammers the platform ALB's AD-group auth
    re-validation on every connection drop instead of backing off, making
    an auth hiccup much more likely to repeat. Sent once per connection,
    before any real events."""
    return f"retry: {delay_ms}\n\n"
