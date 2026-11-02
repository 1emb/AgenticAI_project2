#!/usr/bin/env python3
"""Offline benchmark audit. Reads source; never imports the registrar or calls a model.

Normalization: NFKC, casefold, Unicode alphanumeric word tokens; punctuation,
underscores, apostrophes and hyphens are separators. Compare every sliding
six-token window. Audit question, reason, their concatenation, and the complete
serialized JSON record against source utterances.
"""
from __future__ import annotations

import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import unicodedata

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "runs/codex"
TAGS = set("typo title long two_task action_vs_info own_id incidental_person ta_student authority_claim nonexistent missing_slot crn break_clock contrast_pair greeting".split())
COURSE_LABELS = {"prerequisites", "course_info", "course_offered", "lecture_options", "who_teaches", "capacity", "course_in_plan", "student_list"}


def words(s):
    return re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", s).casefold())


def shingles(s):
    t = words(s)
    return {tuple(t[i:i+6]) for i in range(len(t)-5)}


def spec():
    tree = ast.parse((ROOT / "registrar/agent/intents.py").read_text())
    labels, examples, enums = [], [], {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in {"REGISTRAR_TOPIC_VALUES", "OUTSIDE_TOPIC_VALUES"}:
                    enums[target.id] = ast.literal_eval(node.value)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Intent":
            labels.append("unknown" if isinstance(node.args[0], ast.Name) else ast.literal_eval(node.args[0]))
            examples.extend(ast.literal_eval(node.args[3]))
    assert len(labels) == 20
    return labels, examples, enums


def source_utterances(examples):
    sources = {"intents.py examples": list(examples), "design-review hard-case table": [], "plan.jsonl": [], "data/testset wordings": []}
    review = (OUT / "design-review.md").read_text().split("## 2.", 1)[1].split("## 3.", 1)[0]
    for line in review.splitlines():
        if line.startswith("| ") and not line.startswith("| Question"):
            sources["design-review hard-case table"].append(line.split("|")[1].strip())
    for line in (OUT / "plan.jsonl").read_text().splitlines():
        sources["plan.jsonl"].append(json.loads(line)["question"])
    for path in sorted((ROOT / "data/testset").rglob("*")):
        if path.suffix == ".jsonl":
            for line in path.read_text().splitlines():
                row = json.loads(line)
                if isinstance(row.get("question"), str):
                    sources["data/testset wordings"].append(row["question"])
                ps = row.get("paraphrases", [])
                if isinstance(ps, list):
                    sources["data/testset wordings"].extend(x for x in ps if isinstance(x, str))
        elif path.name == "questions.md":
            sources["data/testset wordings"].extend(path.read_text().splitlines())
    return sources


def audit_rows(rows, prefix, count, labels, enums, sources, strict=True):
    errors = []
    per_label, per_tag, per_topic, titles = Counter(), Counter(), Counter(), Counter()
    seen_q, seen_id = set(), set()
    indexes = {name: set().union(*(shingles(s) for s in utterances)) for name, utterances in sources.items()}
    overlaps = {name: [] for name in indexes}
    long_counts = []
    for i, row in enumerate(rows, 1):
        ident = row.get("id", f"line-{i}")
        allowed = {"id", "question", "expected_intent", "reason", "tags", "family_id", "spec_version", "expected_topic"}
        if set(row)-allowed or not allowed-{"expected_topic"} <= set(row):
            errors.append(f"{ident}: invalid keys")
        if ident != f"{prefix}-{i:03}" or ident in seen_id:
            errors.append(f"{ident}: invalid/duplicate ID")
        seen_id.add(ident)
        label = row.get("expected_intent")
        if label not in labels:
            errors.append(f"{ident}: invalid label")
        per_label[label] += 1
        question, reason = row.get("question", ""), row.get("reason", "")
        if not question.strip() or not reason.strip() or "\n" in question or "\n" in reason:
            errors.append(f"{ident}: empty or multiline prose")
        norm = tuple(words(question))
        if norm in seen_q:
            errors.append(f"{ident}: duplicate normalized question")
        seen_q.add(norm)
        if row.get("spec_version") != "2026-11-02":
            errors.append(f"{ident}: wrong spec version")
        if not isinstance(row.get("family_id"), str) or not row["family_id"].startswith("fam-"):
            errors.append(f"{ident}: invalid family")
        tags = row.get("tags", [])
        if len(tags) != len(set(tags)) or set(tags)-TAGS:
            errors.append(f"{ident}: invalid tags")
        per_tag.update(tags)
        if "title" in tags:
            titles[label] += 1
        if "long" in tags:
            # Word count uses whitespace words, with a stricter normalized check too.
            n = len(question.split())
            long_counts.append(n)
            if not 80 <= n <= 200:
                errors.append(f"{ident}: long tag has {n} words")
        enum_name = {"not_in_data": "REGISTRAR_TOPIC_VALUES", "outside_registrar": "OUTSIDE_TOPIC_VALUES"}.get(label)
        if enum_name:
            if row.get("expected_topic") not in enums[enum_name]:
                errors.append(f"{ident}: invalid/missing readable topic")
            per_topic[(label, row.get("expected_topic"))] += 1
        elif "expected_topic" in row:
            errors.append(f"{ident}: unexpected topic")
        all_s = shingles(question) | shingles(reason) | shingles(question + " " + reason) | shingles(json.dumps(row, ensure_ascii=False))
        for name, index in indexes.items():
            if all_s & index:
                overlaps[name].append(ident)
    if strict:
        if len(rows) != len(labels)*count:
            errors.append(f"{prefix}: wrong row count {len(rows)}")
        for label in labels:
            if per_label[label] != count:
                errors.append(f"{prefix}: {label} has {per_label[label]}, needs {count}")
        for label in COURSE_LABELS:
            if titles[label] < count/3:
                errors.append(f"{prefix}: insufficient titles for {label}")
        for label, key in [("not_in_data", "REGISTRAR_TOPIC_VALUES"), ("outside_registrar", "OUTSIDE_TOPIC_VALUES")]:
            for topic in enums[key]:
                minimum = 2 if prefix == "acc" else 1
                if per_topic[label, topic] < minimum:
                    errors.append(f"{prefix}: insufficient coverage for {label}/{topic}")
        if prefix == "acc":
            for tag in ["typo", "long", "two_task", "action_vs_info"]:
                if per_tag[tag] < 60:
                    errors.append(f"{prefix}: {tag} has {per_tag[tag]}, needs 60")
        family_counts = Counter(r['family_id'] for r in rows)
        for row in rows:
            if 'contrast_pair' in row['tags'] and family_counts[row['family_id']] < 2:
                errors.append(f"{row['id']}: contrast tag has no family partner")
    for name, ids in overlaps.items():
        if ids:
            errors.append(f"{prefix}: six-word overlap against {name}: {','.join(ids)}")
    return {
        "rows": len(rows), "per_label": dict(sorted(per_label.items())),
        "per_tag": {t: per_tag[t] for t in sorted(TAGS)},
        "per_topic": {label: {topic: n for (lab, topic), n in sorted(per_topic.items()) if lab == label} for label in ["not_in_data", "outside_registrar"]},
        "title_counts": dict(sorted(titles.items())),
        "families": len({r["family_id"] for r in rows}),
        "long_word_range": [min(long_counts), max(long_counts)] if long_counts else [],
        "source_overlap_rows": {name: len(ids) for name, ids in overlaps.items()},
        "errors": errors,
    }


def audit_pair(dev_bytes, acc_bytes):
    labels, examples, enums = spec()
    sources = source_utterances(examples)
    results, datasets = {}, {}
    for data, prefix, n in [(dev_bytes, "dev", 12), (acc_bytes, "acc", 30)]:
        if not data.endswith(b'\n'):
            raise ValueError(f'{prefix}: missing terminal newline')
        rows = [json.loads(line) for line in data.decode('utf-8').splitlines()]
        datasets[prefix] = rows
        results[prefix] = audit_rows(rows, prefix, n, labels, enums, sources)
        results[prefix]["sha256"] = hashlib.sha256(data).hexdigest()
    dev, acc = datasets["dev"], datasets["acc"]
    families = {r["family_id"] for r in dev} & {r["family_id"] for r in acc}
    dev_q = {tuple(words(r["question"])) for r in dev}
    duplicates = sum(tuple(words(r["question"])) in dev_q for r in acc)
    cross_shingles = set().union(*(shingles(r["question"]) for r in dev)) & set().union(*(shingles(r["question"]) for r in acc))
    baseline = json.loads((OUT / "evalset-baseline.json").read_text())
    changed = [p for p, h in baseline["tracked_sha256"].items() if not (ROOT/p).is_file() or hashlib.sha256((ROOT/p).read_bytes()).hexdigest() != h]
    review_path = OUT/'evalset-source-review.json'
    reviewed = json.loads(review_path.read_text()) if review_path.exists() else {}
    unreviewed = [p for p in changed if not (ROOT/p).is_file() or hashlib.sha256((ROOT/p).read_bytes()).hexdigest() != reviewed.get('observed_concurrent_sha256', {}).get(p)]
    status_equal = subprocess.check_output(["git", "status", "--short"], cwd=ROOT).decode() == baseline["git_status"]
    results["cross_file"] = {"shared_family_ids": len(families), "duplicate_normalized_questions": duplicates, "shared_question_six_word_shingles": len(cross_shingles)}
    results["workspace"] = {"concurrent_tracked_content_changes_observed": changed, "unreviewed_content_changes": unreviewed, "git_status_unchanged": status_equal}
    results["sources"] = {name: len(values) for name, values in sources.items()}
    results["spec_sha256"] = {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in ["registrar/agent/intents.py", "registrar/agent/llm.py", "registrar/agent/programs.py"]}
    errors = results["dev"]["errors"] + results["acc"]["errors"]
    if families or duplicates or cross_shingles:
        errors.append("Cross-file family, question, or six-word overlap")
    if unreviewed or not status_equal:
        errors.append("Workspace baseline differs")
    results["passed"] = not errors
    return results, errors


def negative_controls():
    labels, examples, enums = spec()
    sources = source_utterances(examples)
    assert words('Six-WORDS, mixed_CASE: One/two THREE') == ['six', 'words', 'mixed', 'case', 'one', 'two', 'three']
    assert shingles('Alpha beta gamma delta epsilon zeta') == shingles('ALPHA-beta, gamma / delta epsilon zeta!')
    passed = []
    for name, utterances in sources.items():
        text = next(s for s in utterances if len(words(s)) >= 6)
        row = dict(id='dev-001', question=text, expected_intent='unknown', reason='Control record for the offline audit.', tags=[], family_id='fam-control', spec_version='2026-11-02')
        r = audit_rows([row], 'dev', 12, labels, enums, {name: [text]}, strict=False)
        assert r['source_overlap_rows'][name] == 1, name
        passed.append(name)
    bad = dict(id='dev-001', question='Please calculate a garden fence length.', expected_intent='not_in_data', reason='Invalid closed topic control.', tags=[], family_id='fam-control', spec_version='2026-11-02', expected_topic='holds_code_that_is_not_readable')
    assert any('invalid/missing readable topic' in e for e in audit_rows([bad], 'dev', 12, labels, enums, {}, strict=False)['errors'])
    bad['expected_intent'] = 'invented_label'
    assert any('invalid label' in e for e in audit_rows([bad], 'dev', 12, labels, enums, {}, strict=False)['errors'])
    return {'normalization': 'passed', 'known_source_leaks_detected': passed, 'invalid_topic_and_label_detected': True}


def main():
    if '--self-test' in sys.argv:
        print(json.dumps(negative_controls(), indent=2))
        return 0
    results, errors = audit_pair((OUT/'classifier-dev.jsonl').read_bytes(), (OUT/'classifier-acceptance.jsonl').read_bytes())
    if '--no-write' not in sys.argv:
        (OUT / "evalset-validation.json").write_text(json.dumps(results, indent=2, ensure_ascii=False)+"\n")
    else:
        saved = json.loads((OUT / "evalset-validation.json").read_text())
        assert results == saved, 'Saved audit differs from the read-only final verification'
    # No held-out wording, reasons, or shingles are printed.
    print(json.dumps({"passed": not errors, "rows": {k: results[k]["rows"] for k in ["dev", "acc"]}, "errors": errors}, indent=2))
    return bool(errors)


if __name__ == "__main__":
    sys.exit(main())
