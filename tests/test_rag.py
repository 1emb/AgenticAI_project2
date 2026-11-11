"""RAG: corpus, hybrid retrieval, fallbacks, access filter, and the tools. No model or database needed: dense retrieval
is exercised with a scripted embedder that returns chosen vectors, so the tests check the plumbing (fusion, caching,
degradation), not embedding quality. Embedding quality is measured by scripts/eval_rag.py against a real model."""
import json

import pytest

from conftest import ROOT
from registrar.agents.policy import PolicyStore
from registrar.rag import CatalogTools, Chunk, HybridRetriever, build_corpus
from registrar.rag.corpus import catalog_chunks, kb_chunks, prerequisite_text
from registrar.rag.retriever import suggest_threshold

CASES = [json.loads(l) for l in open(ROOT / "data/testset/rag/catalog_cases.jsonl")]


@pytest.fixture(scope="module")
def chunks():
    return build_corpus()


class Scripted:
    """Embedder with a fixed vector per text (default: orthogonal junk), counting calls."""
    model = "scripted"

    def __init__(self, vectors=None, fail=False):
        self.vectors, self.fail, self.calls = vectors or {}, fail, 0

    def embed(self, texts, *, query=False):
        self.calls += 1
        if self.fail:
            raise ConnectionError("endpoint down")
        return [self.vectors.get(t, [0.0, 0.0, 1.0]) for t in texts]


# ------------------------------------------------------------------------------------------------ corpus
def test_corpus_sources_and_retired_courses(chunks):
    ids = {c.id for c in chunks}
    assert sum(c.source == "handbook" for c in chunks) == 21
    assert "catalog:CS 3410" in ids and "catalog:CS 2250" not in ids and "catalog:ENG 2450" not in ids  # retired


def test_prerequisite_text_groups():
    rows = [{"required_course_code": "A 1", "min_grade": "C-", "group_number": "1"},
            {"required_course_code": "B 1", "min_grade": "C", "group_number": "2"},
            {"required_course_code": "B 2", "min_grade": "C", "group_number": "2"}]
    assert prerequisite_text(rows) == "Prerequisites: A 1 (grade C- or better) and (B 1 (grade C or better) or B 2 (grade C or better))."
    assert prerequisite_text([]) == "No prerequisites."


def test_catalog_text_states_prerequisites(chunks):
    text = next(c.text for c in chunks if c.id == "catalog:CS 4710")
    assert "CS 3310" in text and "MATH 2530" in text and "upper division" in text


def test_kb_files_are_chunked_and_audience_marked(tmp_path):
    (tmp_path / "faq.md").write_text("## Parking\nPermits are sold online.\n\n## Transcripts\nOrder them from the portal.\n")
    (tmp_path / "staff.md").write_text("<!-- audience: admin -->\n## Override\nAdmins may override a hold.\n")
    out = {c.id: c for c in kb_chunks(tmp_path)}
    assert set(out) == {"kb:faq:1", "kb:faq:2", "kb:staff:1"}
    assert out["kb:faq:1"].audience == "all" and out["kb:staff:1"].audience == "admin"


# ------------------------------------------------------------------------------------------------ lexical
def test_bm25_only_meets_the_labelled_set(chunks):
    r = HybridRetriever(chunks)
    pos = [c for c in CASES if c["expected_courses"]]
    at3 = sum(bool({h["course"] for h in r.search(c["question"], k=3, sources={"catalog"})} & set(c["expected_courses"])) for c in pos)
    assert at3 / len(pos) >= 0.9
    for c in CASES:
        if not c["expected_courses"]:  # off-topic and retired-course questions return nothing, not the nearest course
            assert r.search(c["question"], k=3, sources={"catalog"}) == [], c["question"]


def test_policy_recall_matches_policystore(chunks):
    """Moving the handbook into the hybrid retriever must not lose recall against the existing BM25 PolicyStore."""
    cases = [json.loads(l) for l in open(ROOT / "data/testset/policy/cases.jsonl")]
    r = HybridRetriever(chunks)
    at3 = sum(c["expected_section"] in [h["section"] for h in r.search(c["question"], k=3, sources={"handbook"})] for c in cases)
    at1 = sum(r.search(c["question"], k=1, sources={"handbook"})[0]["section"] == c["expected_section"] for c in cases)
    assert at3 == len(cases) and at1 >= 0.8 * len(cases)


def test_source_filter_and_query_edge_cases(chunks):
    r = HybridRetriever(chunks)
    assert {h["source"] for h in r.search("probation credits", k=5, sources={"handbook"})} == {"handbook"}
    assert r.search("   ") == [] and r.search("x", sources={"nonexistent"}) == []


# ------------------------------------------------------------------------------------------------ access
def test_audience_filter_hides_restricted_chunks_before_ranking():
    pub = Chunk("kb:a:1", "kb", "a: hold", "How students clear a registration hold.")
    adm = Chunk("kb:b:1", "kb", "b: hold override", "Registration hold override procedure for staff.", audience="admin")
    r = HybridRetriever([pub, adm])
    assert [h["id"] for h in r.search("registration hold override", role="student")] == ["kb:a:1"]
    assert [h["id"] for h in r.search("registration hold override", role="instructor")] == ["kb:a:1"]
    assert r.search("registration hold override", role="admin")[0]["id"] == "kb:b:1"


# ------------------------------------------------------------------------------------------------ dense + fusion
def test_dense_finds_what_bm25_cannot(chunks, tmp_path):
    target = next(c for c in chunks if c.id == "catalog:PSY 1110")
    q = "intro class about how people think and behave"
    assert HybridRetriever(chunks).search(q, sources={"catalog"}) == []  # lexical miss (see eval_rag)
    emb = Scripted({target.text: [1.0, 0.0, 0.0], q: [0.9, 0.1, 0.0]})
    r = HybridRetriever(chunks, emb, cache_dir=tmp_path)
    hits = r.search(q, k=3, sources={"catalog"})
    assert hits[0]["id"] == "catalog:PSY 1110" and hits[0]["via"] == ["dense"]


def test_fusion_ranks_agreement_first(chunks, tmp_path):
    a = next(c for c in chunks if c.id == "catalog:CS 3410")   # BM25 best for 'sql'
    b = next(c for c in chunks if c.id == "catalog:CS 5410")   # BM25 second
    emb = Scripted({a.text: [1.0, 0.0, 0.0], b.text: [0.0, 1.0, 0.0], "sql": [0.5, 0.9, 0.0]})
    hits = HybridRetriever(chunks, emb, cache_dir=tmp_path).search("sql", k=2, sources={"catalog"})
    assert {h["id"] for h in hits} == {"catalog:CS 3410", "catalog:CS 5410"}
    assert all(set(h["via"]) == {"bm25", "dense"} for h in hits)


def test_embeddings_are_cached_by_text(chunks, tmp_path):
    e1 = Scripted()
    HybridRetriever(chunks, e1, cache_dir=tmp_path).search("sql")
    assert e1.calls == 2  # one batch call for the corpus, one for the query
    e2 = Scripted()
    HybridRetriever(chunks, e2, cache_dir=tmp_path).search("sql")
    assert e2.calls == 1  # corpus vectors come from disk; only the query is embedded
    edited = chunks[:-1] + [Chunk("catalog:NEW 1", "catalog", "NEW 1 Test", "A brand new course about sql.")]
    e3 = Scripted()
    HybridRetriever(edited, e3, cache_dir=tmp_path).search("sql")
    assert e3.calls == 2  # only the changed chunk is re-embedded (still one extra call), not the whole corpus


def test_failing_embedder_degrades_to_bm25(chunks, tmp_path):
    r = HybridRetriever(chunks, Scripted(fail=True), cache_dir=tmp_path)
    hits = r.search("which course teaches SQL", k=2, sources={"catalog"})
    assert hits[0]["id"] == "catalog:CS 3410" and hits[0]["degraded"] is True and hits[0]["via"] == ["bm25"]
    assert r.has_dense is False


# ------------------------------------------------------------------------------------------------ tools / hook
def test_search_catalog_tool_shape_and_abstention(chunks):
    t = CatalogTools(HybridRetriever(chunks), "student")
    res = t.search_catalog("a class about robots")
    assert res["answer"]["catalog_matches"][0] == "ENG 4510" and res["passages"][0]["course"] == "ENG 4510"
    empty = t.search_catalog("best pizza near campus")
    assert empty["answer"] == {"catalog_matches": []} and "passages" not in empty and "do not suggest" in empty["note"]


def test_policystore_hook_keeps_the_tool_contract(chunks):
    plain = PolicyStore().search_policy("How many credits can a student on probation register for?")
    hooked = PolicyStore(retriever=HybridRetriever(chunks)).search_policy("How many credits can a student on probation register for?")
    assert set(hooked) == set(plain) == {"answer", "passages", "note"}
    assert set(hooked["passages"][0]) == set(plain["passages"][0]) == {"section", "title", "text"}
    assert "3.2" in hooked["answer"]["policy_sections"]
    assert hooked["passages"][0]["title"] == next(p["title"] for p in plain["passages"] if p["section"] == hooked["passages"][0]["section"])


# ------------------------------------------------------------------------------------------------ calibration
def test_min_cosine_makes_dense_abstain(chunks, tmp_path):
    """Without a cutoff dense always returns a nearest neighbour (measured: 0/5 correct abstentions with nomic-embed-text)."""
    q = "best pizza near campus"
    near = next(c for c in chunks if c.id == "catalog:MATH 2210")
    emb = Scripted({near.text: [1.0, 0.0, 0.0], q: [0.4, 0.9165, 0.0]})   # cosine to MATH 2210 is 0.4; to every other chunk 0
    loose = HybridRetriever(chunks, emb, cache_dir=tmp_path, min_cosine=0.0)
    assert loose.search(q, k=3, sources={"catalog"}) != []                 # the failure
    strict = HybridRetriever(chunks, emb, cache_dir=tmp_path, min_cosine=0.5)
    assert strict.search(q, k=3, sources={"catalog"}) == []
    assert strict.top_cosine(q, {"catalog"}) == pytest.approx(0.4, abs=1e-3)


def test_bm25_hit_survives_the_cosine_cutoff(chunks, tmp_path):
    emb = Scripted({"which course teaches SQL": [1.0, 0.0, 0.0]})          # orthogonal to every chunk: cosine 0 < 0.99
    hit = HybridRetriever(chunks, emb, cache_dir=tmp_path, min_cosine=0.99).search("which course teaches SQL", k=2, sources={"catalog"})
    assert hit[0]["id"] == "catalog:CS 3410" and hit[0]["via"] == ["bm25"]


def test_suggest_threshold():
    r = suggest_threshold([0.62, 0.7, 0.8, 0.55], [0.3, 0.41, 0.45])
    assert r["separable"] is True and 0.45 < r["threshold"] <= 0.55 and r["answerable_kept"] == "4/4" and r["unanswerable_rejected"] == "3/3"
    overlap = suggest_threshold([0.5, 0.6, 0.7], [0.55, 0.3])
    assert overlap["separable"] is False
