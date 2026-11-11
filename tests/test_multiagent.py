"""Multi-agent layer: tool ownership, per-agent grounding, agent-to-agent consults, planning, confirmation gate, fallback.
No database or model: a scripted client plays every model turn in order (planner first, then the agents' loops, with a
consulted agent's loop running in the middle of its caller's turn), and tools are stubs. The real Router methods
(_confirm_without_model, _fill_refusal_target, ask) and the real ConfirmationGate are used."""
import json
from types import SimpleNamespace as NS

import pytest

from registrar.agents.loop import ToolLoop
from registrar.agents.multi import AgentRuntime, Coordinator
from registrar.agents.multi.agents import (ADVISING, DATA, NOT_COVERED, NOTHING_CHANGED, POLICY, READS_FOR, REFUSED, REGISTRATION,
                                           UNVERIFIED, agents_available)
from registrar.agents.multi.planner import PlanError, validate_plan
from registrar.agents.registration import ConfirmationGate
from registrar.rag import HybridRetriever, build_corpus
from registrar.agents.router import Router


def call(name, args=None, cid=None):
    return NS(id=cid or f"c_{name}", function=NS(name=name, arguments=json.dumps(args or {})))


class Script:
    """Replays model turns in order. A str is a text reply, a list is tool calls."""

    def __init__(self, turns):
        self.turns, self.requests = list(turns), []
        self.chat = NS(completions=NS(create=self._create))

    def _create(self, **kw):
        self.requests.append({**kw, "messages": [dict(m) for m in kw["messages"]]})
        step = self.turns.pop(0)
        return NS(choices=[NS(message=NS(content=step, tool_calls=None) if isinstance(step, str)
                              else NS(content="", tool_calls=step))])


def spec(name, *params):
    return {"type": "function", "function": {"name": name, "description": name, "parameters": {
        "type": "object", "properties": {p: {"type": "string"} for p in params}, "required": []}}}


STUDENT_TOOLS = ["get_course_info", "get_course_sections", "get_section", "get_my_registrations", "get_my_transcript", "get_my_gpa", "decline_request",
                 "plan_my_degree", "check_course_in_my_plan", "search_policy", "search_catalog",
                 "check_registration", "request_registration", "request_drop", "confirm_change", "cancel_change"]
INSTRUCTOR_TOOLS = ["get_my_sections", "get_my_roster", "get_my_advisees", "plan_for_advisee", "search_policy",
                    "search_catalog", "request_grade", "confirm_change", "cancel_change", "decline_request"]
ADMIN_TOOLS = ["grade_distribution", "at_risk_students", "search_policy", "search_catalog"]

GPA = {"answer": {"cumulative_gpa": 3.5, "last_term": "Fall 2025", "last_term_gpa": 3.7, "credits_earned": 60}}
PLAN = {"answer": {"status": "ok", "earliest_graduation_term": "Spring 2028", "remaining_required": ["CS 4910"],
                   "next_term": "Spring 2027", "next_term_courses": ["CS 3410"]},
        "plan": [{"term": "Spring 2027", "projected": False, "credits": 15, "courses": ["CS 3410"], "crns": ["10011"]},
                 {"term": "Fall 2027", "projected": True, "credits": 15, "courses": ["CS 4910"], "crns": []}],
        "assumptions": ["Fall 2027 sections are not published yet"], "blockers": []}
HITS = {"answer": {"policy_sections": ["4.1"]}, "passages": [{"section": "4.1", "title": "Academic standing", "text": "..."}]}
NO_HITS = {"answer": {"policy_sections": []}, "note": "No handbook section matches"}


@pytest.fixture(scope="module")
def chunks():
    return build_corpus()


def make_router(role="student", tools=None, results=None, script=()):
    names = tools or {"student": STUDENT_TOOLS, "instructor": INSTRUCTOR_TOOLS, "admin": ADMIN_TOOLS}[role]
    results = results or {}
    log = []

    def dispatch(name, args):
        log.append((name, args))
        r = results.get(name, {"answer": {}})
        return r(args) if callable(r) else r

    client = Script(script)
    loop = ToolLoop(client, "fake", "PERSONA PROMPT", [spec(n, "x") for n in names], dispatch)
    r = object.__new__(Router)
    r.role, r.uid, r.gate, r.writer = role, "800000001", ConfirmationGate(), NS(confirm_change=None)
    r.agent = NS(loop=loop, tools=None, ask=lambda q: NS(reply="LEGACY", calls=[], steps=1, stopped_early=False))
    r.base_prompt = "PERSONA BASE PROMPT"
    return r, client, log


def plan(*tasks):
    return json.dumps({"tasks": [{"agent": a, "question": q} for a, q in tasks]})


def sent_tools(req):
    return {t["function"]["name"] for t in req.get("tools") or []}


# ------------------------------------------------------------------------------------------------ ownership
def test_every_tool_has_exactly_one_owner_and_roles_get_their_agents():
    for role, avail in (("student", [DATA, POLICY, ADVISING, REGISTRATION]), ("instructor", [DATA, POLICY, ADVISING, REGISTRATION]),
                        ("admin", [DATA, POLICY])):
        r, _, _ = make_router(role)
        rt = AgentRuntime(r)
        assert rt.available == avail == agents_available(r)
        owned = {}
        for a in rt.available:
            for t in rt.tools_of(a):
                if t != "decline_request" and not (a in READS_FOR and t in READS_FOR[a]):   # shared read-only lookups
                    assert owned.setdefault(t, a) == a, f"{t} owned twice"
        assert set(owned) == set(rt.specs) - {"decline_request"}          # nothing orphaned
    r, _, _ = make_router()
    rt = AgentRuntime(r)
    assert "request_registration" not in rt.tools_of(DATA) and "get_my_gpa" in rt.tools_of(DATA)
    assert "decline_request" in rt.tools_of(POLICY)


def test_admin_has_no_registration_agent_and_instructor_advising_works():
    r, client, _ = make_router("admin", script=[plan(("policy", "x"))])
    co = Coordinator(r)
    with pytest.raises(PlanError):
        validate_plan({"tasks": [{"agent": "registration", "question": "drop it"}]}, co.runtime.available)
    r, client, log = make_router("instructor", results={"get_my_advisees": {"answer": {"advisees": ["A"]}}},
                                 script=[plan(("advising", "Who are my advisees?")), [call("get_my_advisees")], "You advise A."])
    res = Coordinator(r).ask("Who are my advisees?")                      # this path crashed in the orchestrator (bug B1)
    assert res.route == "multi" and res.answer["advisees"] == ["A"] and log == [("get_my_advisees", {})]


# ------------------------------------------------------------------------------------------------ planning + delegation
def test_single_task_data_agent_with_deterministic_gpa():
    r, client, log = make_router(results={"get_my_gpa": GPA}, script=[plan((DATA, "What is my GPA?")),
                                 [call("get_my_gpa")], "Your GPA is a totally different number 2.0."])
    res = Coordinator(r).ask("What is my GPA?")
    assert res.reply.startswith("Cumulative GPA: 3.50") and "2.0" not in res.reply     # facts from the tool, not the prose
    assert res.plan == [{"agent": "data", "question": "What is my GPA?"}] and res.answer["cumulative_gpa"] == 3.5
    first = client.requests[1]                                                          # the data agent's own loop
    assert first["messages"][0]["content"].count("PERSONA BASE PROMPT") == 1 and "Data agent" in first["messages"][0]["content"]
    assert "request_registration" not in sent_tools(first) and "search_policy" not in sent_tools(first)


def test_agents_receive_what_earlier_agents_verified():
    r, client, _ = make_router(results={"get_my_gpa": GPA, "plan_my_degree": PLAN},
                               script=[plan((DATA, "What is my GPA?"), (ADVISING, "What should I take next?")),
                                       [call("get_my_gpa")], "ok", [call("plan_my_degree")], "Take CS 3410."])
    res = Coordinator(r).ask("What is my GPA and what should I take next?")
    advising_user_msg = client.requests[3]["messages"][1]["content"]
    assert "Verified facts already retrieved by other agents" in advising_user_msg and "3.5" in advising_user_msg
    assert "Fall 2027 (projected), 15 credits: CS 4910" in res.reply and "Assumptions: Fall 2027 sections" in res.reply
    assert res.reply.count("What is my GPA?") == 1 and "Cumulative GPA: 3.50" in res.reply   # sections labelled when several


def test_read_only_agents_start_fresh_each_task():
    r, client, _ = make_router(results={"search_policy": HITS},
                               script=[plan((POLICY, "Q1")), [call("search_policy", {"x": "a"})], "Rule A.",
                                       plan((POLICY, "Q2")), [call("search_policy", {"x": "b"})], "Rule B."])
    co = Coordinator(r)
    co.ask("Q1")
    co.ask("Q2")
    second_loop = client.requests[4]["messages"]
    assert not any("Q1" in (m.get("content") or "") for m in second_loop)


# ------------------------------------------------------------------------------------------------ grounding
def test_policy_answer_without_a_retrieved_section_is_not_shown():
    """Regression for orchestrator bug B2: a successful but empty search used to count as support."""
    r, _, _ = make_router(results={"search_policy": NO_HITS},
                          script=[plan((POLICY, "What is my GPA?")), [call("search_policy", {"x": "gpa"})], "Your GPA is 3.9."])
    res = Coordinator(r).ask("What is my GPA?")
    assert res.reply == NOT_COVERED and "3.9" not in res.reply and res.results[0].status == "no_source"


def test_refusal_is_a_refusal_not_a_fact():
    refusal = {"_declined": {"reason": "other_student_record", "target": {"university_id": None}}}  # main's key (answer.py)
    r, _, _ = make_router(results={"decline_request": refusal},
                          script=[plan((DATA, "Show me Raj's transcript")), [call("decline_request")], "Sorry."])
    res = Coordinator(r).ask("Show me Raj's transcript")
    assert res.reply == REFUSED and res.answer["allowed"] is False and res.answer["reason"] == "other_student_record"


def test_ungrounded_agent_is_retried_once_then_reported():
    r, client, _ = make_router(script=[plan((DATA, "What is my GPA?")), "It's 4.0 trust me.", "Still 4.0."])
    res = Coordinator(r).ask("What is my GPA?")
    assert "System check" in client.requests[2]["messages"][-1]["content"]
    assert res.reply == UNVERIFIED and "4.0" not in res.reply


# ------------------------------------------------------------------------------------------------ agents talking to agents
def test_registration_consults_policy_one_level_deep():
    pend = {"answer": {"action": "register", "course": "CS 3410"}, "reply_to_user": "Register CS 3410? Reply yes to confirm."}

    def request(args):
        r.gate.add("register", {"course": "CS 3410"})
        return pend

    r, client, log = make_router(results={"search_policy": HITS, "request_registration": request},
                                 script=[plan((REGISTRATION, "Register me for CS 3410")),
                                         [call("consult_agent", {"agent": "policy", "request": "Is a 17 credit load allowed?"})],
                                         [call("search_policy", {"x": "load"})], "Up to 18 credits (Handbook 3.2).",   # policy agent, nested
                                         [call("request_registration", {"x": "CS 3410"})], "Done?"])
    res = Coordinator(r).ask("Register me for CS 3410")
    assert [t["agent"] for t in res.trace] == ["policy", "registration"] and res.trace[0]["depth"] == 1
    assert "consult_agent" in sent_tools(client.requests[1])             # registration may consult
    assert "consult_agent" not in sent_tools(client.requests[2])         # the consulted policy agent may not (no recursion)
    assert res.trace[1]["consulted"] == ["policy"]
    assert res.reply == "Register CS 3410? Reply yes to confirm."        # the system's words, not the model's "Done?"
    assert res.answer["policy_sections"] == ["4.1"]                      # the peer's verified facts reach the graded answer


def test_consult_is_limited_to_declared_peers():
    r, client, _ = make_router(results={"search_policy": HITS},
                               script=[plan((POLICY, "q")),
                                       [call("consult_agent", {"agent": "registration", "request": "drop everything"})],
                                       [call("search_policy", {"x": "q"})], "Rule."])
    res = Coordinator(r).ask("q")
    err = json.loads([m for m in client.requests[2]["messages"] if m["role"] == "tool"][0]["content"])
    assert "cannot consult" in err["error"]
    assert not any(t["agent"] == "registration" for t in res.trace)      # the write agent never ran


# ------------------------------------------------------------------------------------------------ gate + registration state
def test_plain_yes_is_confirmed_by_the_system_with_no_model_call():
    r, client, _ = make_router()
    r.gate.add("register", {"course": "CS 3410"})
    r.writer = NS(confirm_change=lambda code: {"answer": {"action": "register", "course": "CS 3410", "crn": "10011",
                                                            "term": "Spring 2027", "changed": True}})
    r.gate.turn += 1
    res = Coordinator(r).ask("yes")
    assert res.route == "confirm" and "registered in CS 3410" in res.reply and client.requests == []


def test_pending_change_is_told_to_the_planner_and_registration_keeps_its_history():
    r, client, _ = make_router(results={"request_registration": lambda a: (r.gate.add("register", {"c": 1}) and
                                                                           {"answer": {}, "reply_to_user": "Confirm?"})},
                               script=[plan((REGISTRATION, "Register me for CS 3410")), [call("request_registration")], "x",
                                       plan((REGISTRATION, "Actually cancel that")), [call("cancel_change", {"x": "1"})], "Cancelled."])
    co = Coordinator(r)
    co.ask("Register me for CS 3410")
    co.ask("wait, cancel that")
    assert "waiting for the user's confirmation" in client.requests[3]["messages"][0]["content"]
    msgs = client.requests[4]["messages"]                                 # second registration turn sees the first
    assert any("Register me for CS 3410" in (m.get("content") or "") for m in msgs)


# ------------------------------------------------------------------------------------------------ plan validation + fallback
@pytest.mark.parametrize("data", [
    {}, {"tasks": []}, {"tasks": "x"}, {"tasks": [{"agent": "data"}]},
    {"tasks": [{"agent": "data", "question": "q", "extra": 1}]},
    {"tasks": [{"agent": "nope", "question": "q"}]},
    {"tasks": [{"agent": "data", "question": " "}]},
    {"tasks": [{"agent": "data", "question": "q"}] * 2},
    {"tasks": [{"agent": "data", "question": str(i)} for i in range(4)]},
    {"tasks": [{"agent": "registration", "question": "a"}, {"agent": "data", "question": "b"}]},      # write must be last
    {"tasks": [{"agent": "registration", "question": "a"}, {"agent": "registration", "question": "b"}]},
    {"action": "orchestrate", "tasks": [{"agent": "data", "question": "q"}]},
])
def test_invalid_plans_are_rejected(data):
    with pytest.raises(PlanError):
        validate_plan(data, [DATA, POLICY, ADVISING, REGISTRATION])


def test_bad_planner_output_falls_back_to_the_persona_agent():
    r, client, _ = make_router(script=["this is not json"])
    res = Coordinator(r).ask("anything")
    assert res.route == "fallback" and res.reply == "LEGACY"


# ------------------------------------------------------------------------------------------------ fixes from the first live run
def test_registration_can_look_up_sections_itself_and_shows_a_tool_error():
    """Live run (llama3.1:8b): 'Register me for CS 5810' passed the course code as a CRN, and the user only saw 'couldn't verify'."""
    from registrar.agents.common import ToolError

    def no_such_crn(args):
        raise ToolError("CRN CS 5810 does not exist in Spring 2027.")       # real tools raise; the loop turns it into an error result

    r, client, _ = make_router(results={"request_registration": no_such_crn},
                               script=[plan((REGISTRATION, "Register me for CS 5810")),
                                       [call("request_registration", {"x": "CS 5810"})], "Done.", "Sorry."])
    rt_tools = AgentRuntime(r).tools_of(REGISTRATION)
    assert {"get_course_sections", "get_my_registrations"} <= set(rt_tools)
    assert "get_course_sections" in AgentRuntime(r).tools_of(DATA)               # data keeps them too
    res = Coordinator(r).ask("Register me for CS 5810")
    assert res.reply == "I couldn't make that change: CRN CS 5810 does not exist in Spring 2027."


def test_planner_prompt_routes_rule_questions_to_policy():
    """Live run: 'How many credits can I take if I'm on probation?' went to data and got a wrong, ungrounded-in-policy answer."""
    r, client, _ = make_router(script=[plan((POLICY, "q")), [call("search_policy", {"x": "q"})], "r"], results={"search_policy": HITS})
    Coordinator(r).ask("q")
    system = client.requests[0]["messages"][0]["content"]
    assert "what the rules ALLOW or REQUIRE" in system and "probation" in system and '"agent":"policy"' in system


# ------------------------------------------------------------------------------------------------ fixes from the second live run
SECTION_10032 = {"answer": {"course": "CS 5810", "term": "Spring 2027", "offered": True, "crns": ["10032"],
                            "sections": [{"crn": "10032", "section_number": "M01"}]}}


def _pending_registration(r):
    def request(args):
        r.gate.add("register", {"crn": args["crn"]})
        return {"pending_change": {"code": "ABC123"}, "reply_to_user": f"I can register you in CS 5810 (CRN {args['crn']}). Shall I go ahead?"}
    return request


def test_course_to_pending_change_in_one_tool_call():
    """Live run: llama looked up the sections, asked 'shall I?' and never prepared the change, so 'yes' had nothing to confirm."""
    holder = {}
    r, client, log = make_router(results={"get_course_sections": SECTION_10032,
                                          "request_registration": lambda a: holder["req"](a)},
                                 script=[plan((REGISTRATION, "Register me for CS 5810")),
                                         [call("request_registration_for_course", {"course": "CS 5810", "term": "next spring"})],
                                         "Would you like me to go ahead?"])
    holder["req"] = _pending_registration(r)
    res = Coordinator(r).ask("Register me for CS 5810")
    assert [n for n, _ in log] == ["get_course_sections", "request_registration"] and log[1][1]["crn"] == "10032"
    assert res.reply == "I can register you in CS 5810 (CRN 10032). Shall I go ahead?" and r.gate.pending   # a real pending change


def test_several_sections_are_listed_not_guessed_and_unoffered_courses_are_reported():
    r, client, log = make_router(results={"get_course_sections": {"answer": {"course": "CS 3410", "term": "Spring 2027", "crns": ["1", "2"],
                                                                      "sections": [{"crn": "1"}, {"crn": "2"}]}}},
                                 script=[plan((REGISTRATION, "Register me for CS 3410")),
                                         [call("request_registration_for_course", {"course": "CS 3410"})], "Which section: 1 or 2?"])
    res = Coordinator(r).ask("Register me for CS 3410")
    assert [n for n, _ in log] == ["get_course_sections"] and not r.gate.pending and res.reply == "Which section: 1 or 2?"
    r, client, log = make_router(results={"get_course_sections": {"answer": {"course": "CS 5810", "term": "Spring 2027", "offered": False, "crns": []}}},
                                 script=[plan((REGISTRATION, "Register me for CS 5810")),
                                         [call("request_registration_for_course", {"course": "CS 5810"})], "Not offered.", "Not offered."])
    assert Coordinator(r).ask("Register me for CS 5810").reply == "I couldn't make that change: CS 5810 is not offered in Spring 2027."


def test_a_completion_claim_with_no_write_is_replaced():
    """Live run: after 'yes' with nothing pending, the model faked a confirm_change code (the gate refused it), called get_section,
    and wrote 'You are registered for CS 5810'. Nothing had changed."""
    from registrar.agents.common import ToolError

    def refuse(args):
        raise ToolError("There is no pending change with that code. Request the change again.")

    r, client, _ = make_router(results={"confirm_change": refuse, "get_section": {"answer": {"crn": "10032", "course": "CS 5810"}}},
                               script=[plan((REGISTRATION, "Please confirm my registration now")),
                                       [call("confirm_change", {"code": "pending registration code"}), call("get_section", {"crn": "10032"})],
                                       "You are registered for CS 5810, Section M01."])
    res = Coordinator(r).ask("Please confirm my registration now")
    assert res.reply == NOTHING_CHANGED and "registered" not in res.reply.replace("register for", "")
    assert not res.answer.get("changed")


def test_a_real_change_is_reported_in_the_systems_words():
    done = {"answer": {"action": "register", "course": "CS 5810", "crn": "10032", "term": "Spring 2027", "changed": True}}
    r, client, _ = make_router(results={"confirm_change": done},
                               script=[plan((REGISTRATION, "Go ahead and register me")), [call("confirm_change", {"code": "ABC123"})], "All set, enjoy!!"])
    assert Coordinator(r).ask("Go ahead and register me").reply == "You are registered in CS 5810 (CRN 10032), Spring 2027."


def test_bare_yes_with_nothing_pending_gets_a_clear_message_and_no_model_call():
    r, client, _ = make_router()
    res = Coordinator(r).ask("yes")
    assert "no pending change" in res.reply and res.route == "confirm" and client.requests == []


# ------------------------------------------------------------------------------------------------ catalog precision
class VecEmbedder:
    """Embedder with a fixed vector per text (default: orthogonal junk)."""
    model = "vec"

    def __init__(self, vectors):
        self.vectors = vectors

    def embed(self, texts, *, query=False):
        return [self.vectors.get(t, [0.0, 0.0, 1.0]) for t in texts]


def _catalog_tools(chunks, tmp_path, vectors, min_cosine=0.5):
    from registrar.rag import CatalogTools, HybridRetriever
    return CatalogTools(HybridRetriever(chunks, VecEmbedder(vectors), cache_dir=tmp_path, min_cosine=min_cosine), "student")


def test_keyword_matches_beat_semantic_only_neighbours(tmp_path):
    """Live run: 'databases' also returned CS 2210 Data Structures, which the model then explained away."""
    chunks = build_corpus()
    t = {c.id: c.text for c in chunks}
    tools = _catalog_tools(chunks, tmp_path, {t["catalog:CS 3410"]: [1, 0, 0], t["catalog:CS 2210"]: [0.8, 0.6, 0], "databases": [1, 0, 0]})
    assert tools.retriever.search("databases", k=5, sources={"catalog"})[-1]["id"] == "catalog:CS 2210"       # the retriever does return it
    assert tools.search_catalog("databases")["answer"]["catalog_matches"] == ["CS 3410", "CS 5410"]          # the tool does not


def test_dense_only_hits_must_clear_the_dense_only_floor(chunks, tmp_path, monkeypatch):
    t = next(c.text for c in chunks if c.id == "catalog:PSY 1110")
    q = "intro class about how people think and behave"
    tools = _catalog_tools(chunks, tmp_path, {t: [1, 0, 0], q: [0.65, 0.76, 0]})                              # cosine 0.65
    monkeypatch.setenv("EMBED_DENSE_ONLY_MIN", "0.6")
    assert tools.search_catalog(q)["answer"]["catalog_matches"] == ["PSY 1110"]
    monkeypatch.setenv("EMBED_DENSE_ONLY_MIN", "0.7")
    assert tools.search_catalog(q)["answer"] == {"catalog_matches": []}


def test_hits_expose_their_cosine(chunks, tmp_path):
    t = next(c.text for c in chunks if c.id == "catalog:CS 3410")
    hit = HybridRetriever(chunks, VecEmbedder({t: [1, 0, 0], "sql": [1, 0, 0]}), cache_dir=tmp_path).search("sql", k=1, sources={"catalog"})[0]
    assert hit["cosine"] == 1.0
