"""The Policy agent's retrieval layer: BM25 over the sections of data/policy/handbook.md, plus the machine-readable
parameters in data/policy/params.json.

- search(query) returns the best handbook sections with their section ids, so every rule an agent states can be
  cited. It is exposed to every persona agent as the tool `search_policy`.
- get_params() returns typed values for code that applies rules (the Advising planner, the Admin standing reports).
  Numbers that change outcomes come from params.json, never from an LLM reading the text; the text supplies the
  citation. tests/test_policy.py checks that the two agree.

Dense embeddings were not used: this container cannot download an embedding model reliably, and BM25 alone reaches
the recall reported by tests/test_policy.py on this 22-section corpus. A dense retriever can be added in search().
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HANDBOOK = ROOT / "data/policy/handbook.md"
PARAMS = ROOT / "data/policy/params.json"
STOP = set("a an the of to in on for and or is are be by with as at it its this that which what who whom how do does "
           "did can i my me we our you your their they them when where than then there from into not no any".split())
SYNONYMS = {"probation": ["standing"], "suspended": ["suspension"], "suspension": ["suspended"],
            "gpa": ["grade", "point", "average"], "drop": ["dropped", "withdraw"], "withdraw": ["w", "withdrawn"],
            "repeat": ["retake", "repeated"], "retake": ["repeat"], "load": ["credit", "hours"],
            "fulltime": ["full", "time"], "graduate": ["graduation", "master"], "prerequisite": ["prerequisites"],
            "phone": ["directory", "private"], "advisor": ["privacy", "record"], "overload": ["load", "limit"],
            "take": ["register"]}


def _tokens(text: str) -> list[str]:
    out = []
    for w in re.findall(r"[a-z0-9]+", text.lower().replace("full-time", "fulltime")):
        if w in STOP:
            continue
        w = w[:-1] if len(w) > 4 and w.endswith("s") and not w.endswith("ss") else w
        out.append(w)
    return out


@dataclass
class Section:
    id: str
    title: str
    text: str


def load_sections(path: Path = HANDBOOK) -> list[Section]:
    secs, cur = [], None
    for line in path.read_text().splitlines():
        m = re.match(r"##\s+(\d+\.\d+)\s+(.*)", line)
        if m:
            cur = Section(m.group(1), m.group(2).strip(), "")
            secs.append(cur)
        elif cur is not None and line.strip():
            cur.text = (cur.text + " " + line.strip()).strip()
    return secs


class PolicyStore:
    def __init__(self, handbook: Path = HANDBOOK, params: Path = PARAMS, k1: float = 1.4, b: float = 0.6):
        self.sections = load_sections(handbook)
        self.params = json.loads(params.read_text())
        self.k1, self.b = k1, b
        self.docs = [_tokens(s.title) * 3 + _tokens(s.text) for s in self.sections]  # title weighted
        self.avgdl = sum(map(len, self.docs)) / len(self.docs)
        df = Counter(t for d in self.docs for t in set(d))
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
        self.tf = [Counter(d) for d in self.docs]

    def _score(self, q: list[str], i: int) -> float:
        tf, dl, s = self.tf[i], len(self.docs[i]), 0.0
        for t in q:
            if t in tf:
                f = tf[t]
                s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
        return s

    def search(self, query: str, k: int = 3) -> list[dict]:
        q = _tokens(query)
        q += [syn for t in list(q) for syn in SYNONYMS.get(t, [])]
        ranked = sorted(range(len(self.sections)), key=lambda i: (-self._score(q, i), self.sections[i].id))
        return [{"section": self.sections[i].id, "title": self.sections[i].title, "text": self.sections[i].text}
                for i in ranked[:k] if self._score(q, i) > 0]

    def section(self, sid: str) -> Section | None:
        return next((s for s in self.sections if s.id == sid), None)

    # ---------------------------------------------------------------- PolicyTools for the Advising agent
    def get_params(self) -> dict:
        return {k: v for k, v in self.params.items() if not k.startswith("_") and k != "sections"}

    def cite(self, keys: list[str]) -> list[dict]:
        out = []
        for k in keys:
            sid = self.params.get("sections", {}).get(k)
            s = self.section(sid) if sid else None
            if s:
                out.append({"key": k, "source": f"Synthetic Registrar Handbook, Sec. {s.id} {s.title}", "text": s.text})
        return out

    # ---------------------------------------------------------------- tool for the persona agents
    def search_policy(self, question: str) -> dict:
        hits = self.search(question)
        if not hits:
            return {"answer": {"policy_sections": []}, "note": "No handbook section matches; say the handbook does "
                                                               "not cover it."}
        return {"answer": {"policy_sections": [h["section"] for h in hits]}, "passages": hits,
                "note": "Answer only from these passages and cite the section number (e.g. 'Handbook 3.2')."}


SEARCH_POLICY_SPEC = {"type": "function", "function": {
    "name": "search_policy",
    "description": "Search the registrar handbook for a rule: grading, GPA, repeating courses, course load limits, "
                   "full-time status, probation and suspension, prerequisites, course levels, add/drop/withdraw, "
                   "degree requirements, graduation, privacy. Returns the matching sections; cite them.",
    "parameters": {"type": "object", "properties": {
        "question": {"type": "string", "description": "The rule the user asks about, in their words."}},
        "required": ["question"]}}}
