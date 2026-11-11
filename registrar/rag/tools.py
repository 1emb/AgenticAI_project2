"""search_catalog: the retrieval tool for 'which course covers ...' questions. Structured lookups by code or title stay with
get_course_info; this finds courses by what they are about, which SQL cannot do."""
from __future__ import annotations

import os

from registrar.rag.retriever import HybridRetriever


class CatalogTools:
    def __init__(self, retriever: HybridRetriever, role: str):
        self.retriever, self.role = retriever, role

    def search_catalog(self, topic: str) -> dict:
        hits = self.retriever.search(topic, k=5, sources={"catalog"}, role=self.role)
        # Precision. A keyword match is strong evidence; a semantic-only neighbour is weak (live run: 'databases' also
        # returned Data Structures). So keyword hits win outright, and when there are none, semantic-only hits must clear
        # EMBED_DENSE_ONLY_MIN (a stricter cosine than the general cutoff; measure it with eval_rag.py --query).
        lexical = [h for h in hits if "bm25" in h["via"]]
        if lexical:
            hits = lexical
        else:
            floor = float(os.environ.get("EMBED_DENSE_ONLY_MIN", "0"))
            hits = [h for h in hits if h.get("cosine", 1.0) >= floor]
        if not hits:
            return {"answer": {"catalog_matches": []},
                    "note": "No course in the catalog matches that topic; say so and do not suggest a course."}
        return {"answer": {"catalog_matches": [h["course"] for h in hits]},
                "passages": [{"course": h["course"], "title": h["title"], "text": h["text"]} for h in hits],
                "note": "These are the closest catalog entries, best first; some may be weak matches. List a course only if "
                        "its text is about the topic, by code, and say only what its text says. "
                        "Use get_course_info for sections and schedules, and plan_my_degree for whether it fits the degree."}


SEARCH_CATALOG_SPEC = {"type": "function", "function": {
    "name": "search_catalog",
    "description": "Find courses by subject matter, e.g. 'which courses cover databases', 'a class about robots', "
                   "'something on writing'. Returns the closest catalog entries (code, title, description, "
                   "prerequisites). For a known course code or title use get_course_info instead.",
    "parameters": {"type": "object", "properties": {
        "topic": {"type": "string", "description": "The subject the user wants a course about, in their words."}},
        "required": ["topic"]}}}
