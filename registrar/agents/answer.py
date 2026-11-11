"""Turn the tool calls of one turn into the graded JSON answer (data/testset/README.md, Verification contract).

  - no refusal:   {"allowed": true, **facts from the data tools}
  - refusal:      {"allowed": false, "reason", "target", "own_answer": facts from data tools (if any)}

Data tools put facts under "answer"; decline tools put the refusal under "_declined" (kept from the model by the
loop). Later results override earlier ones on the same key; failed calls are ignored.
"""
from __future__ import annotations

from registrar.agents.loop import ToolCall


def assemble_answer(calls: list[ToolCall]) -> dict:
    facts: dict = {}
    refusal: dict | None = None
    for call in calls:
        if not call.ok:
            continue
        if "answer" in call.result:
            facts.update(call.result["answer"])
        if "_declined" in call.result:
            refusal = call.result["_declined"]
    if refusal is None:
        return {"allowed": True, **facts}
    out = {"allowed": False, "reason": refusal["reason"], "target": refusal["target"]}
    if facts:
        out["own_answer"] = facts
    return out
