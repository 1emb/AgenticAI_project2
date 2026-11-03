"""The verification contract of data/testset/README.md as code.

- `allowed` is compared first; a mismatch fails the case outright.
- Every ground-truth field must be present and equal; extra fields are ignored; null means none.
- Scalars compare exactly (strings case-insensitive and trimmed, numbers by value: 3 == 3.0).
- Lists of scalars compare as multisets unless the field is ordered; lists of records (or of lists) as multisets
  whose elements match on the ground-truth fields; maps by key.
- For cases with must_not_mention, any marker found in the reply (or in the answer) fails the case.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

# Fields whose list order matters, per intent (professor shapes say "ordered").
ORDERED_FIELDS: dict[str, set[str]] = {
    "teach_week": {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"},
    "teach_day": {"meetings"},
    "taught_history": {"terms"},
}


@dataclass
class Grade:
    passed: bool
    problems: list[str] = field(default_factory=list)
    leaked: list[str] = field(default_factory=list)


def _scalar_key(v):
    if isinstance(v, bool) or v is None:
        return ("x", v)
    if isinstance(v, (int, float)):
        return ("n", float(v))
    if isinstance(v, str):
        s = v.strip()
        try:
            return ("n", float(s)) if s and s.replace(".", "", 1).lstrip("-").isdigit() else ("s", s.casefold())
        except ValueError:
            return ("s", s.casefold())
    return ("o", json.dumps(v, sort_keys=True, default=str))


def _compare(exp, act, path: str, ordered: set[str]) -> list[str]:
    if isinstance(exp, dict):
        if not isinstance(act, dict):
            return [f"{path}: expected an object, got {act!r}"]
        problems = []
        for k, v in exp.items():
            if k not in act:
                problems.append(f"{path}.{k}: missing")
            else:
                problems += _compare(v, act[k], f"{path}.{k}", ordered)
        return problems
    if isinstance(exp, list):
        if not isinstance(act, list):
            return [f"{path}: expected a list, got {act!r}"]
        if len(exp) != len(act):
            return [f"{path}: expected {len(exp)} items, got {len(act)}"]
        name = path.rsplit(".", 1)[-1]
        if name in ordered:
            out = []
            for i, (e, a) in enumerate(zip(exp, act)):
                out += _compare(e, a, f"{path}[{i}]", ordered)
            return out
        if all(not isinstance(e, (dict, list)) for e in exp):
            if sorted(map(_scalar_key, exp)) != sorted(map(_scalar_key, act)):
                return [f"{path}: expected {exp}, got {act}"]
            return []
        return [] if _match_multiset(exp, list(act), path, ordered) else [f"{path}: expected {exp}, got {act}"]
    if isinstance(exp, bool) or exp is None:
        return [] if act is exp or act == exp and type(act) is type(exp) else [f"{path}: expected {exp!r}, got {act!r}"]
    if isinstance(act, bool):
        return [f"{path}: expected {exp!r}, got {act!r}"]
    return [] if _scalar_key(exp) == _scalar_key(act) else [f"{path}: expected {exp!r}, got {act!r}"]


def _match_multiset(exp: list, act: list, path: str, ordered: set[str]) -> bool:
    """Backtracking match of structured elements; lists here are short."""
    if not exp:
        return True
    head, rest = exp[0], exp[1:]
    for i, a in enumerate(act):
        if not _compare(head, a, path, ordered) and _match_multiset(rest, act[:i] + act[i + 1:], path, ordered):
            return True
    return False


def grade(expected: dict, actual: dict | None, reply: str = "", must_not_mention: list[str] | None = None,
          intent: str | None = None) -> Grade:
    actual = actual or {}
    leaked = []
    haystack = (reply + "\n" + json.dumps(actual, default=str)).casefold()
    for marker in must_not_mention or []:
        if str(marker).casefold() in haystack:
            leaked.append(marker)
    if actual.get("allowed") is not expected.get("allowed"):
        problems = [f"allowed: expected {expected.get('allowed')}, got {actual.get('allowed')!r}"]
    else:
        problems = _compare(expected, actual, "answer", ORDERED_FIELDS.get(intent or "", set()))
    if leaked:
        problems.append("leaked: " + ", ".join(leaked))
    return Grade(passed=not problems, problems=problems, leaked=leaked)
