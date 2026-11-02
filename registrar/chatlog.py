"""Append-only record of every question asked interactively, and the verdicts given on the answers.

    runs/chat.jsonl (override with CHAT_LOG in .env or the environment); one JSON object per line, two kinds:
      {"kind": "ask", "id", "ts", "source", "student": {...}, "as_of", "question", ...the trace: intent, intent_confidence,
       mentions, resolved, answer, reply, error, failed_stage, sql, timings}
      {"kind": "verdict", "id": <the ask's id>, "ts", "verdict", "note", "by"}
    `by` is who judged: "owner" from the page, or a judge name such as "codex" for verdicts imported with
    scripts/import_verdicts.py. The latest verdict for an id wins; an empty verdict clears it. load() merges them.

Writers (the web UI, scripts/ask.py) append under a file lock, so several processes can share the file. grade.py does not
write here: its runs go to runs/<persona>-<timestamp>.jsonl.
"""
from __future__ import annotations

import fcntl
import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from .testset.common import Encoder

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
LOG_PATH = Path(os.environ.get("CHAT_LOG", ROOT / "runs" / "chat.jsonl"))

VERDICTS = ("correct", "wrong", "should_refuse", "should_answer")
_lock = threading.Lock()


def _append(rec: dict) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(rec, cls=Encoder, ensure_ascii=False) + "\n"
    with _lock, open(LOG_PATH, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(line)
        fcntl.flock(f, fcntl.LOCK_UN)


def record(trace, source: str, student: dict | None = None) -> str:
    """Append a question and its trace; returns the id the verdict refers to."""
    rid = uuid.uuid4().hex[:12]
    d = trace.to_dict()
    rec = {"kind": "ask", "id": rid, "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "source": source,
           "student": student or d.pop("user"), **{k: v for k, v in d.items() if k != "user"}}
    _append(rec)
    return rid


def record_verdict(rid: str, verdict: str | None, note: str | None = None, by: str = "owner") -> dict:
    if verdict and verdict not in VERDICTS:
        raise ValueError(f"verdict must be one of {VERDICTS} or empty")
    rec = {"kind": "verdict", "id": rid, "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "verdict": verdict or None,
           "note": (note or "").strip() or None, "by": (by or "owner").strip().lower()}
    _append(rec)
    return rec


def load(path: Path = None) -> list[dict]:
    """Every ask, oldest first, with `verdict`, `note`, `verdict_by` and `verdict_ts` merged in from the latest verdict record."""
    path = path or LOG_PATH
    if not path.exists():
        return []
    asks: dict[str, dict] = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("kind") == "ask":
                asks[r["id"]] = {**r, "verdict": None, "note": None, "verdict_by": None, "verdict_ts": None}
            elif r.get("kind") == "verdict" and r.get("id") in asks:
                asks[r["id"]].update(verdict=r.get("verdict"), note=r.get("note"), verdict_by=r.get("by") or "owner", verdict_ts=r.get("ts"))
    return list(asks.values())


def outcome(r: dict) -> str:
    """answered | refused | clarify | unknown | error, from the recorded answer."""
    a = r.get("answer")
    if r.get("error") and not a:
        return "error"
    if a is None:
        return "error"
    if a.get("allowed") is False:
        return "refused"
    if a.get("error") == "missing_slot":
        return "clarify"
    if a.get("unknown"):
        return "unknown"
    return "answered"
