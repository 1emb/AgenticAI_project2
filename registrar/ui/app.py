"""A small FastAPI app: pick a student and a clock, ask a question, read the reply and the trace behind it.

    python scripts/ui.py                 # http://127.0.0.1:8080

Endpoints: GET / (the page), GET /api/students, GET /api/clocks, GET /api/examples, GET /api/health, POST /api/ask,
POST /api/verdict, GET /api/history, GET /api/history/{id}. Every question and its trace is appended to runs/chat.jsonl
(registrar/chatlog.py); the verdict buttons on the page append to the same file, and the History view reads it back.
Every request opens its own database connection; the LLM client is shared (it is stateless). Needs Postgres (./db/start.sh)
and the vLLM server (scripts/serve_llm.sh). No authentication: the student is chosen from a list, this is a simulation.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from ..agent.intents import STUDENT_INTENTS
from ..agent.llm import Client, LLMError
from ..agent.pipeline import answer_question
from ..agent.reply import write_reply
from .. import chatlog
from ..db import DATABASE_URL
from ..testset.common import AS_OF_BREAK, AS_OF_LATE, AS_OF_SPRING, DEFAULT_AS_OF, SNAPSHOT, Encoder, connect

DSN = DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")
STATIC = Path(__file__).resolve().parent / "static"

CLOCKS = [
    {"as_of": DEFAULT_AS_OF, "label": "Default: Fall 2026 in progress, Spring 2027 registration open", "default": True},
    {"as_of": SNAPSHOT, "label": "Mid Fall 2026: withdraw deadline ahead, registration not yet open"},
    {"as_of": AS_OF_LATE, "label": "Late Fall 2026: classes end Dec 11"},
    {"as_of": AS_OF_BREAK, "label": "Winter break: Fall 2026 over, current term is Spring 2027"},
    {"as_of": AS_OF_SPRING, "label": "Spring 2027 in session, add deadline Jan 22 ahead"},
]

app = FastAPI(title="Registrar assistant")
llm = Client()


class Ask(BaseModel):
    question: str
    university_id: str
    as_of: str | None = None
    reply: bool = True


class Verdict(BaseModel):
    id: str
    verdict: str | None = None       # correct | wrong | should_refuse | should_answer | null to clear
    note: str | None = None


def _dump(o) -> JSONResponse:
    return JSONResponse(json.loads(json.dumps(o, cls=Encoder, ensure_ascii=False)))


def _clock(s: str | None) -> datetime:
    if not s:
        return DEFAULT_AS_OF
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(400, f"as_of is not an ISO 8601 datetime: {s}")
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/students")
def students():
    with connect(DSN) as conn, conn.cursor() as cur:
        cur.execute("""SELECT p.university_id, p.first_name, p.last_name, s.program_code, s.status
                       FROM student s JOIN person p ON p.university_id = s.university_id
                       ORDER BY p.last_name, p.first_name, p.university_id""")
        rows = cur.fetchall()
    return [{"university_id": r[0], "name": f"{r[1]} {r[2]}", "program_code": r[3], "status": r[4]} for r in rows]


@app.get("/api/clocks")
def clocks():
    return _dump(CLOCKS)


@app.get("/api/examples")
def examples():
    return [{"intent": i.name, "question": q} for i in STUDENT_INTENTS for q in i.examples if i.name not in ("unknown",)]


@app.get("/api/health")
def health():
    out = {"database": "ok", "llm": "ok", "model": llm.model, "llm_url": llm.base_url}
    try:
        with connect(DSN) as conn, conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM student")
            out["students"] = cur.fetchone()[0]
    except psycopg.Error as e:
        out["database"] = f"error: {e}".split("\n")[0]
    try:
        served = llm.ping()
        if llm.model not in served:
            out["llm"] = f"error: model {llm.model} not served (served: {', '.join(served)})"
    except LLMError as e:
        out["llm"] = f"error: {e}"
    return out


@app.post("/api/ask")
def ask(body: Ask):
    q = body.question.strip()
    if not q:
        raise HTTPException(400, "empty question")
    as_of = _clock(body.as_of)
    try:
        with connect(DSN) as conn:
            t = answer_question(conn, llm, q, body.university_id, as_of)
    except ValueError as e:                       # unknown student
        raise HTTPException(404, str(e))
    except psycopg.Error as e:
        raise HTTPException(503, f"database: {e}".split("\n")[0])
    if body.reply:
        write_reply(llm, t)
    rid = chatlog.record(t, "ui")
    return _dump({**t.to_dict(), "id": rid})


@app.post("/api/verdict")
def verdict(body: Verdict):
    try:
        return chatlog.record_verdict(body.id, body.verdict, body.note)
    except ValueError as e:
        raise HTTPException(400, str(e))


def _lean(r: dict) -> dict:
    st = r.get("student") or {}
    return {"id": r["id"], "ts": r["ts"], "source": r.get("source"), "student": st, "as_of": r.get("as_of"), "question": r.get("question"),
            "intent": r.get("intent"), "intent_confidence": r.get("intent_confidence"), "outcome": chatlog.outcome(r), "reply": r.get("reply"),
            "error": r.get("error"), "verdict": r.get("verdict"), "note": r.get("note"), "total_s": round(sum((r.get("timings") or {}).values()), 2)}


@app.get("/api/history")
def history(student: str | None = None, intent: str | None = None, verdict: str | None = None, outcome: str | None = None,
            q: str | None = None, since: str | None = None, limit: int = 500):
    """Newest first. verdict=unjudged selects rows without one."""
    rows = chatlog.load()
    if student:
        rows = [r for r in rows if (r.get("student") or {}).get("university_id") == student]
    if intent:
        rows = [r for r in rows if r.get("intent") == intent]
    if verdict == "unjudged":
        rows = [r for r in rows if not r.get("verdict")]
    elif verdict:
        rows = [r for r in rows if r.get("verdict") == verdict]
    if outcome:
        rows = [r for r in rows if chatlog.outcome(r) == outcome]
    if since:
        rows = [r for r in rows if r["ts"] >= since]
    if q:
        ql = q.lower()
        rows = [r for r in rows if ql in (r.get("question") or "").lower() or ql in (r.get("reply") or "").lower() or ql in (r.get("note") or "").lower()]
    total = len(rows)
    return {"total": total, "rows": [_lean(r) for r in rows[::-1][:limit]], "log": str(chatlog.LOG_PATH)}


@app.get("/api/history/{rid}")
def history_one(rid: str):
    for r in chatlog.load():
        if r["id"] == rid:
            return r
    raise HTTPException(404, f"no record {rid}")
