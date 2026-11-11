"""Run clingo on advising.lp + facts. Returns optimal plans, cautious first-term courses, and relaxations."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

import clingo

ENCODING = Path(__file__).parent / "asp" / "advising.lp"


@dataclass
class Model:
    take: dict[str, int] = field(default_factory=dict)  # course -> term index
    sec: dict[tuple[str, int], str] = field(default_factory=dict)  # (course, term) -> crn
    load: dict[int, int] = field(default_factory=dict)
    grad: int | None = None
    cost: list[int] = field(default_factory=list)


@dataclass
class SolveResult:
    satisfiable: bool
    optimal: bool
    models: list[Model]
    cautious_first_term: list[str] | None  # None = not proven within the time limit
    seconds: float
    timed_out: bool = False  # True: the best plan's lower-priority objectives are not proven optimal
    graduation_proven: bool = False  # True: no plan ends earlier


def _parse(symbols) -> Model:
    m = Model()
    for s in symbols:
        a = s.arguments
        if s.name == "take":
            m.take[a[0].string] = a[1].number
        elif s.name == "sec":
            m.sec[(a[0].string, a[1].number)] = a[2].string
        elif s.name == "load":
            m.load[a[0].number] = a[1].number
        elif s.name == "grad":
            m.grad = a[0].number
    return m


def _control(facts: str, extra: list[str]) -> clingo.Control:
    ctl = clingo.Control(["--opt-mode=optN", "--models=0", "--project=show", *extra], logger=lambda c, m: None)
    ctl.load(str(ENCODING))
    ctl.add("base", [], facts)
    ctl.ground([("base", [])])
    return ctl


def solve(facts: str, num_plans: int = 3, timeout_s: float = 10.0, grad_lb: int | None = None) -> SolveResult:
    t0 = time.perf_counter()
    models: list[Model] = []
    optimal = False

    best: list[Model] = []  # last model seen = best so far (clingo improves monotonically)

    def on_model(mdl: clingo.Model):
        nonlocal optimal
        if not mdl.optimality_proven:
            b = _parse(mdl.symbols(shown=True))
            b.cost = list(mdl.cost)
            best[:] = [b]
        if mdl.optimality_proven:
            optimal = True
            if len(models) < num_plans:
                m = _parse(mdl.symbols(shown=True))
                m.cost = list(mdl.cost)
                models.append(m)
            return len(models) < num_plans
        return True

    ctl = _control(facts + "all_objectives.\n", [])
    with ctl.solve(on_model=on_model, async_=True) as h:
        finished = h.wait(timeout_s)
        if not finished:
            h.cancel()
        res = h.get()
    if not res.satisfiable and not best:
        # unknown (timeout, no model yet) must not be read as unsatisfiable
        return SolveResult(False, False, [], [], time.perf_counter() - t0, timed_out=bool(res.unknown))
    if not models:  # timeout before optimality was proven: return the best plan found, flagged
        models = best

    cautious: list[str] = []
    ctl2 = _control(facts, ["--enum-mode=cautious"])  # graduation objective only (no all_objectives)
    last = []

    def on_cautious(mdl: clingo.Model):
        nonlocal last
        if mdl.optimality_proven:
            last = list(mdl.symbols(shown=True))
        return True

    cautious_done = True
    with ctl2.solve(on_model=on_cautious, async_=True) as h2:
        if not h2.wait(timeout_s):
            h2.cancel()
            cautious_done = False  # an unfinished cautious set is a superset: not sound to report
        h2.get()
    cautious = (sorted(s.arguments[0].string for s in last if s.name == "take" and s.arguments[1].number == 1)
                if cautious_done and last else None)
    grad_proven = optimal or (grad_lb is not None and models and models[0].grad == grad_lb)
    return SolveResult(True, optimal, models, cautious, time.perf_counter() - t0, timed_out=not optimal,
                       graduation_proven=bool(grad_proven))
