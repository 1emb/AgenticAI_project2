"""Evaluate retrieval on the labelled sets, BM25-only versus hybrid (hybrid needs EMBED_MODEL, see registrar/rag/retriever.py).

    python scripts/eval_rag.py                              # BM25 only
    EMBED_MODEL=nomic-embed-text python scripts/eval_rag.py # BM25 and hybrid side by side
    python scripts/eval_rag.py --show-misses
    EMBED_MODEL=... python scripts/eval_rag.py --calibrate   # choose EMBED_MIN_COSINE from your own data
    EMBED_MODEL=... python scripts/eval_rag.py --query "is there a course on surveying"   # raw scores for one question

Sets: data/testset/policy/cases.jsonl (question -> handbook section) and data/testset/rag/catalog_cases.jsonl
(question -> acceptable course codes; off_topic and retired cases must return nothing). Metrics: recall@1 and recall@3
(an expected item in the top 1 / 3), and, for the cases that must return nothing, the share that correctly does.
"""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from registrar.rag import HybridRetriever, build_corpus  # noqa: E402
from registrar.rag.retriever import OpenAICompatEmbedder, suggest_threshold  # noqa: E402


def load(p):
    return [json.loads(l) for l in open(ROOT / p)]


def run(ret: HybridRetriever, show: bool) -> dict:
    out = {}
    pol = load("data/testset/policy/cases.jsonl")
    ranks = [[h["section"] for h in ret.search(c["question"], k=3, sources={"handbook"})] for c in pol]
    out["policy recall@1"] = sum(r[:1] == [c["expected_section"]] for r, c in zip(ranks, pol)) / len(pol)
    out["policy recall@3"] = sum(c["expected_section"] in r for r, c in zip(ranks, pol)) / len(pol)
    if show:
        for r, c in zip(ranks, pol):
            if c["expected_section"] not in r[:1]:
                print(f"  policy {c['id']}: want {c['expected_section']}, got {r}  | {c['question']}")
    cat = load("data/testset/rag/catalog_cases.jsonl")
    pos = [c for c in cat if c["expected_courses"]]
    neg = [c for c in cat if not c["expected_courses"]]
    got = {c["id"]: [h["course"] for h in ret.search(c["question"], k=3, sources={"catalog"})] for c in cat}
    out["catalog recall@1"] = sum(bool(set(got[c["id"]][:1]) & set(c["expected_courses"])) for c in pos) / len(pos)
    out["catalog recall@3"] = sum(bool(set(got[c["id"]]) & set(c["expected_courses"])) for c in pos) / len(pos)
    out["correctly empty (off-topic/retired)"] = sum(not got[c["id"]] for c in neg) / len(neg)
    if show:
        for c in pos:
            if not set(got[c["id"]][:3]) & set(c["expected_courses"]):
                print(f"  catalog {c['id']}: want {c['expected_courses']}, got {got[c['id']]}  | {c['question']}")
        for c in neg:
            if got[c["id"]]:
                print(f"  should be empty {c['id']}: got {got[c['id']]}  | {c['question']}")
    return out


def calibrate(ret: HybridRetriever) -> None:
    """Dense retrieval always returns a nearest neighbour, so 'nothing matches' needs a cosine cutoff. Measure the best
    cosine of questions that have an answer versus questions that must return nothing, and suggest the cutoff."""
    pos, neg = [], []
    for c in load("data/testset/policy/cases.jsonl"):
        pos.append(ret.top_cosine(c["question"], {"handbook"}))
    for c in load("data/testset/rag/catalog_cases.jsonl"):
        if c["expected_courses"]:
            pos.append(ret.top_cosine(c["question"], {"catalog"}))
        elif c["kind"] == "off_topic":   # the retired-course case is a near miss, not off-topic; kept out of the fit
            neg.append(ret.top_cosine(c["question"]))
    if None in pos + neg:
        sys.exit("dense retrieval is not available (is EMBED_MODEL set and the endpoint up?)")
    q = lambda xs, f: sorted(xs)[int(f * (len(xs) - 1))]
    print(f"answerable questions   top cosine: min {min(pos):.3f}  p10 {q(pos, .1):.3f}  median {q(pos, .5):.3f}")
    print(f"off-topic questions    top cosine: max {max(neg):.3f}  median {q(neg, .5):.3f}   (n={len(neg)})")
    r = suggest_threshold(pos, neg)
    print(f"\nsuggested EMBED_MIN_COSINE={r['threshold']}  keeps {r['answerable_kept']} answerable, rejects "
          f"{r['unanswerable_rejected']} off-topic" + ("" if r["separable"] else "  (the two ranges overlap: expect some errors)"))
    print("Then rerun without --calibrate to confirm. The cutoff applies to the dense half only; a BM25 match still counts.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--show-misses", action="store_true")
    ap.add_argument("--calibrate", action="store_true")
    ap.add_argument("--query", help="show how one question ranks: keyword vs semantic evidence and the raw cosine of each hit")
    a = ap.parse_args()
    chunks = build_corpus()
    if a.query:
        emb = OpenAICompatEmbedder.from_env()
        ret = HybridRetriever(chunks, emb, min_cosine=0.0)   # raw view: no cutoff, so you can choose one
        for src in ("catalog", "handbook"):
            print(f"-- {src}")
            for h in ret.search(a.query, k=6, sources={src}):
                print(f"  {h['id']:22} via={'+'.join(h['via']):10} cosine={h.get('cosine', '-')}  {h['title'][:50]}")
        return
    if a.calibrate:
        emb = OpenAICompatEmbedder.from_env()
        if not emb:
            sys.exit("set EMBED_MODEL first")
        return calibrate(HybridRetriever(chunks, emb, min_cosine=0.0))
    systems = {"bm25": HybridRetriever(chunks)}
    emb = OpenAICompatEmbedder.from_env()
    if emb:
        cutoff = float(os.environ.get("EMBED_MIN_COSINE", "0"))   # same variable the chat path reads (get_retriever)
        systems[f"hybrid ({emb.model}, cutoff {cutoff:g})"] = HybridRetriever(chunks, emb, min_cosine=cutoff)
    else:
        print("EMBED_MODEL not set: BM25 only. Set it to compare against hybrid retrieval.\n")
    res = {}
    for name, ret in systems.items():
        print(f"== {name}")
        res[name] = run(ret, a.show_misses)
        if ret.embedder and not ret.has_dense:
            print("  WARNING: the embedding endpoint failed; these numbers are BM25 only.")
    metrics = next(iter(res.values())).keys()
    print(f"\n{'metric':40}" + "".join(f"{n:>40}" for n in res))
    for m in metrics:
        print(f"{m:40}" + "".join(f"{res[n][m]:>40.2f}" for n in res))


if __name__ == "__main__":
    main()
