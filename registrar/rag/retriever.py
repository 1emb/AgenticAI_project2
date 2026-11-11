"""Hybrid retrieval: BM25 (lexical) + dense embeddings (semantic), fused with reciprocal rank fusion.

Why both: BM25 is exact on rule wording and course codes ("C- or better", "CS 3410") and returns nothing when the query
shares no words with the corpus, which is the right behaviour for an off-topic question. Embeddings catch paraphrase
("how do computers talk over the internet" -> Computer Networks) that BM25 misses. Fusing ranks, not scores, avoids
having to calibrate two incomparable score scales.

Dense retrieval is optional. Set EMBED_MODEL (and EMBED_BASE_URL if it is not the LLM server) and any OpenAI-compatible
/embeddings endpoint is used: Ollama (`ollama pull nomic-embed-text`) or vLLM (`vllm serve <embedding model>`). With no
EMBED_MODEL, or if the endpoint fails, the retriever runs BM25-only and marks the hits `degraded`, never raising into
the agent loop. Chunk embeddings are cached on disk keyed by model + text hash, so only new or edited chunks are embedded.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Protocol

from registrar.agents.policy import SYNONYMS, _tokens
from registrar.rag.corpus import ROOT, Chunk, build_corpus

log = logging.getLogger(__name__)

# Query-side expansions for catalog wording; the handbook ones come from registrar.agents.policy.SYNONYMS.
CATALOG_SYNONYMS = {"ml": ["machine", "learning"], "ai": ["artificial", "intelligence"], "nlp": ["natural", "language"],
                    "os": ["operating", "system"], "db": ["database"], "sql": ["database", "relational"],
                    "coding": ["programming"], "robot": ["robotics"], "cybersecurity": ["security"],
                    "encryption": ["cryptography"], "internet": ["network"], "networking": ["network"],
                    "thesis": ["research", "thesis"], "capstone": ["project", "capstone"]}
RRF_K = 60


class Embedder(Protocol):
    model: str

    def embed(self, texts: list[str], *, query: bool = False) -> list[list[float]]: ...


class OpenAICompatEmbedder:
    """POST {base_url}/embeddings. `query_prefix` / `doc_prefix` exist because some models (nomic-embed-text, e5) are
    trained with task prefixes such as 'search_query: ' and 'search_document: '."""

    def __init__(self, base_url: str, model: str, api_key: str = "ollama", timeout: float = 60.0,
                 query_prefix: str = "", doc_prefix: str = "", batch: int = 32):
        self.base_url, self.model, self.api_key, self.timeout = base_url.rstrip("/"), model, api_key, timeout
        self.query_prefix, self.doc_prefix, self.batch = query_prefix, doc_prefix, batch

    @classmethod
    def from_env(cls) -> "OpenAICompatEmbedder | None":
        model = os.environ.get("EMBED_MODEL")
        if not model:
            return None
        base = os.environ.get("EMBED_BASE_URL") or os.environ.get("LLM_BASE_URL", "http://127.0.0.1:11434/v1")
        return cls(base, model, os.environ.get("EMBED_API_KEY", os.environ.get("LLM_API_KEY", "ollama")),
                   query_prefix=os.environ.get("EMBED_QUERY_PREFIX", ""), doc_prefix=os.environ.get("EMBED_DOC_PREFIX", ""))

    def embed(self, texts: list[str], *, query: bool = False) -> list[list[float]]:
        prefix = self.query_prefix if query else self.doc_prefix
        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch):
            body = json.dumps({"model": self.model, "input": [prefix + t for t in texts[i:i + self.batch]]}).encode()
            req = urllib.request.Request(self.base_url + "/embeddings", body, {
                "Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"})
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                data = json.load(r)["data"]
            out += [d["embedding"] for d in sorted(data, key=lambda d: d["index"])]
        return out


def _unit(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


class HybridRetriever:
    LEX_FLOOR = 0.2   # absolute BM25 floor
    LEX_REL = 0.2     # fraction of the best BM25 score a hit must reach

    def __init__(self, chunks: list[Chunk], embedder: Embedder | None = None, cache_dir: Path | None = None,
                 k1: float = 1.4, b: float = 0.6, min_cosine: float = 0.0):
        self.chunks, self.embedder, self.k1, self.b, self.min_cosine = chunks, embedder, k1, b, min_cosine
        self.cache_dir = cache_dir if cache_dir is not None else ROOT / ".rag_cache"
        # Title counted three times, as in PolicyStore (chunk.text already holds it once, so add it twice more), so a query
        # naming a course or section finds it first. Statistics (idf, average length) are kept per source: the handbook
        # and the catalog are separate collections, and a word rare in one is common in the other.
        self._docs = [_tokens(c.title) * 2 + _tokens(c.text) for c in chunks]
        self._tf = [Counter(d) for d in self._docs]
        self._idf: dict[str, dict[str, float]] = {}
        self._avgdl: dict[str, float] = {}
        for src in {c.source for c in chunks}:
            idx = [i for i, c in enumerate(chunks) if c.source == src]
            df = Counter(t for i in idx for t in set(self._docs[i]))
            n = len(idx)
            self._idf[src] = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
            self._avgdl[src] = sum(len(self._docs[i]) for i in idx) / n
        self._vecs: list[list[float]] | None = None
        self._dense_failed = False
        self._warned = False

    @property
    def has_dense(self) -> bool:
        return self.embedder is not None and not self._dense_failed

    # ------------------------------------------------------------------------------------------ lexical
    def _expand(self, query: str) -> list[str]:
        q = _tokens(query)
        syn = {**SYNONYMS, **CATALOG_SYNONYMS}
        # expansions go through the same tokenizer/stemmer as the corpus, or 'robotics' would never match 'robotic'
        return q + [s for t in list(q) for s in _tokens(" ".join(syn.get(t, [])))]

    def _bm25(self, q: list[str], i: int) -> float:
        src = self.chunks[i].source
        tf, dl, idf, avgdl, s = self._tf[i], len(self._docs[i]), self._idf[src], self._avgdl[src], 0.0
        for t in q:
            if t in tf:
                f = tf[t]
                s += idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / avgdl))
        return s

    def _lexical_ranking(self, query: str, allowed: list[int]) -> list[int]:
        q = self._expand(query)
        scored = sorted(((self._bm25(q, i), i) for i in allowed), key=lambda x: (-x[0], self.chunks[x[1]].id))
        # A word found in nearly every chunk ('course', 'credit') scores ~0 but not exactly 0 and would pad the list with
        # noise, so drop hits below an absolute floor and below a fraction of the best hit.
        top = scored[0][0] if scored else 0.0
        return [i for s, i in scored if s >= max(self.LEX_FLOOR, self.LEX_REL * top)]

    # ------------------------------------------------------------------------------------------ dense
    def _key(self, c: Chunk) -> str:
        return hashlib.sha256(f"{self.embedder.model}\0{c.text}".encode()).hexdigest()[:24]

    def _build_dense(self) -> None:
        cache_file = self.cache_dir / (re.sub(r"[^\w.-]", "_", self.embedder.model) + ".json")
        cache: dict[str, list[float]] = {}
        try:
            cache = json.loads(cache_file.read_text())
        except (OSError, ValueError):
            pass
        keys = [self._key(c) for c in self.chunks]
        missing = [i for i, k in enumerate(keys) if k not in cache]
        if missing:
            fresh = self.embedder.embed([self.chunks[i].text for i in missing])
            for i, v in zip(missing, fresh):
                cache[keys[i]] = _unit(v)
            try:
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                live = set(keys)  # drop vectors of chunks that no longer exist
                cache_file.write_text(json.dumps({k: v for k, v in cache.items() if k in live}))
            except OSError:
                log.warning("RAG: could not write embedding cache %s", cache_file)
        self._vecs = [cache[k] for k in keys]

    def _dense_scored(self, query: str, allowed: list[int]) -> list[tuple[float, int]] | None:
        """(cosine, chunk index) best first, or None when dense retrieval is off or just failed."""
        if not self.has_dense:
            return None
        try:
            if self._vecs is None:
                self._build_dense()
            qv = _unit(self.embedder.embed([query], query=True)[0])
        except Exception as e:  # noqa: BLE001 - endpoint down, model missing, bad response: degrade, never raise
            self._dense_failed = True
            if not self._warned:
                log.warning("RAG: dense retrieval disabled, using BM25 only (%s: %s)", type(e).__name__, e)
                self._warned = True
            return None
        scored = [(sum(a * b for a, b in zip(qv, self._vecs[i])), i) for i in allowed]
        return sorted(scored, key=lambda x: (-x[0], self.chunks[x[1]].id))

    def _dense_ranking(self, query: str, allowed: list[int]) -> list[int] | None:
        scored = self._dense_scored(query, allowed)
        return None if scored is None else [i for s, i in scored if s >= self.min_cosine]

    def top_cosine(self, query: str, sources: set[str] | None = None, role: str = "student") -> float | None:
        """Best dense cosine for the query over the given sources, for calibrating min_cosine (None without dense)."""
        allowed = [i for i, c in enumerate(self.chunks)
                   if c.audience in ("all", role) and (sources is None or c.source in sources)]
        scored = self._dense_scored(query, allowed) if allowed else None
        return scored[0][0] if scored else None

    # ------------------------------------------------------------------------------------------ search
    def search(self, query: str, k: int = 4, sources: set[str] | None = None, role: str = "student") -> list[dict]:
        """Top-k chunks as dicts (id, source, title, text, score, via). `role` filters by chunk audience first, so a
        restricted chunk is never even ranked for someone outside its audience."""
        allowed = [i for i, c in enumerate(self.chunks)
                   if c.audience in ("all", role) and (sources is None or c.source in sources)]
        if not allowed or not query.strip():
            return []
        lex = self._lexical_ranking(query, allowed)
        scored = self._dense_scored(query, allowed)
        dense = None if scored is None else [i for sc, i in scored if sc >= self.min_cosine]
        cos = {i: sc for sc, i in scored} if scored else {}
        score: dict[int, float] = {}
        via: dict[int, list[str]] = {}
        for name, ranking in (("bm25", lex), ("dense", dense or [])):
            for rank, i in enumerate(ranking[: max(k * 4, 20)], start=1):
                score[i] = score.get(i, 0.0) + 1.0 / (RRF_K + rank)
                via.setdefault(i, []).append(name)
        top = sorted(score, key=lambda i: (-score[i], self.chunks[i].id))[:k]
        degraded = self.embedder is not None and dense is None
        return [{**self.chunks[i].as_hit(), "score": round(score[i], 5), "via": via[i],
                 **({"cosine": round(cos[i], 3)} if i in cos else {}), **({"degraded": True} if degraded else {})}
                for i in top]


def suggest_threshold(positive: list[float], negative: list[float]) -> dict:
    """Pick the cosine cutoff that keeps the most answerable questions while rejecting the most unanswerable ones.
    positive: top cosine of questions that have an answer; negative: top cosine of questions that must return nothing.
    A cutoff c keeps a question when its cosine >= c. Ties go to the lower cutoff (fewer false rejections)."""
    if not positive or not negative:
        raise ValueError("need both answerable and off-topic examples to calibrate")
    cands = sorted(set(positive) | set(negative))
    best = None
    for c in cands:
        kept = sum(x >= c for x in positive)
        rejected = sum(x < c for x in negative)
        # balanced accuracy: the answerable set is much larger than the off-topic set, so raw counts would never reject anything
        score = (kept / len(positive) + rejected / len(negative), -c)
        if best is None or score > best[0]:
            best = (score, c, kept, rejected)
    _, c, kept, rejected = best
    return {"threshold": round(c, 3), "answerable_kept": f"{kept}/{len(positive)}",
            "unanswerable_rejected": f"{rejected}/{len(negative)}",
            "separable": min(positive) > max(negative) if positive and negative else None}


_cache: dict[tuple, HybridRetriever] = {}


def get_retriever(session=None) -> HybridRetriever:
    """One shared retriever per process: the corpus is static between restarts, and dense vectors are costly to rebuild."""
    emb = OpenAICompatEmbedder.from_env()
    key = (emb.model if emb else None, session is not None)
    if key not in _cache:
        _cache[key] = HybridRetriever(build_corpus(session), emb, min_cosine=float(os.environ.get("EMBED_MIN_COSINE", "0")))
    return _cache[key]
