# Classifier evaluation sets

Independent question sets for stage 1 of the agent (the label a question gets), written by Codex (gpt-6.1-sol, max reasoning)
against the label definitions in `registrar/agent/intents.py` and the rules in `CLASSIFY_SYSTEM` (`registrar/agent/llm.py`),
following the protocol in its design review (`runs/codex/design-review.md`, section 4, git-ignored). They are classifier inputs,
not database fixtures: entities may be misspelt, nonexistent or ambiguous, because the label does not depend on existence.

| File | Rows | Use |
|---|---:|---|
| `dev.jsonl` | 246 | Development: definitions are iterated against it. 240 written by Codex (12 per label) plus the 6 rows the first acceptance run missed (`dev-from-acc-*`). |
| `hard-cases.jsonl` | 52 | The boundary cases from the design review, section 2 (development). |
| `acceptance.jsonl` | 600 | Acceptance v1 (30 per label), frozen and read-only. Spent as a blind check on 2026-11-02 (below); kept as a regression benchmark. |
| `acceptance-v2.jsonl` | 600 | Acceptance v2 (30 per label, spec 2026-11-02b), frozen and read-only, families disjoint from v1 and dev. Run 2026-11-02 (below); its misses have **not** been read, so it is still blind. |
| `check_evalsets.py` | | Codex's self-check: schema, balance, coverage, family separation, six-word-shingle overlap with every prohibited source. |

Record: `{"id", "question", "expected_intent", "reason", "tags", "family_id", "spec_version"}`.

2026-11-02 relabel: the owner folded `not_in_data` and `outside_registrar` into `unknown` ("everything that is not in the intents we
have prepared"). Every row carrying one of those two labels had its `expected_intent` field rewritten to `unknown` and its
`expected_topic` field removed, by a script that touched no other field and printed no question text, so the acceptance files
stay blind. `unknown` therefore has 3× the rows of every other label (36 in dev, 90 in each acceptance set); the per-label
threshold for it is 95% of its row count (86/90). The 20-label files and the topic-choice scores are in commit `c436eef`.

## Running
```bash
python scripts/grade.py --cases data/testset/classifier/dev.jsonl --confusion            # one run, confusion matrix
python scripts/grade.py --cases data/testset/classifier/acceptance.jsonl --confusion --repeat 2 --quiet   # the acceptance protocol
```
`--cases` classifies only (no extraction, no database). `--repeat 2` runs the file twice and lists predictions that differ.
`--quiet` hides the failing questions, which is how an acceptance file stays unread by the implementer.

## Reliability criterion
On a frozen acceptance file, under frozen definitions, model, decoding and server settings: at least 588/600 overall, at least
95% for every label (29/30; 86/90 for `unknown`), zero answerable catalog/lecture/calendar/degree-plan questions sent to
`unknown`, and the same result on two consecutive runs. Definitions are iterated against `dev.jsonl` only, by changing label
descriptions and rules, never by adding examples that match evaluation wording. If acceptance misses are read to guide a change,
they move into `dev.jsonl` and a fresh blind acceptance file is needed for the next claim.

## Results
| Date | File | Definitions | Result |
|---|---|---|---|
| 2026-11-02 | `acceptance.jsonl` (v1, sha256 `39c6a6c9…`) | before the first-request rule rewrite | 594/600 on both runs, identical predictions, every label ≥ 29/30, topic choice 60/60. **Failed** the zero-false-referral clause: 4 answerable rows (prerequisites, lecture_meeting, capacity, course_in_plan) went to `not_in_data`; the other 2 misses were person_info→student_list and unknown→not_in_data. Full matrix in `acceptance-v1-report.txt`; Codex's construction report in `codex-evalset-report.md`. |
| 2026-11-02 | `dev.jsonl` + `hard-cases.jsonl` | after the rewrite | 246/246 and 52/52, identical on two runs; 467/467 on the generated student questions and paraphrases; 156/156 end to end. |
| 2026-11-02 | `acceptance-v2.jsonl` (sha256 `5306a7c4…`) | after the rewrite (intents.py `84afed94…`, llm.py `cd5e9d88…`) | 591/600 on both runs, identical predictions, topic choice 60/60. **Failed** two clauses: `unknown` recall 25/30 (5 unknown rows labelled not_in_data ×2, capacity, lecture_meeting, term_dates), and 3 answerable rows sent to `not_in_data` (course_offered, lecture_meeting, my_program); plus one register_when→term_dates. Matrix in `acceptance-v2-report.txt`; construction report in `codex-acceptance-v2-report.md`. The misses were not read, so v2 can still serve as a blind check after definition changes made against dev only. |
| 2026-11-02 | `acceptance-v2.jsonl` relabelled to 18 labels (sha256 `06226329…`) | referral labels folded into `unknown` (intents.py `840d269e…`, llm.py `cf101984…`) | 594/600 on both runs, identical predictions, every label ≥ 29/30 and `unknown` 87/90. **Failed** the zero-false-unknown clause by 2 rows: lecture_meeting→unknown ×1, current_term→unknown ×1; the other misses are register_when→term_dates ×1 and unknown→capacity / lecture_meeting / course_info ×1 each. Matrix in `acceptance-v2-report-18labels.txt`. Misses still not read; v2 remains blind. Same day: dev 246/246, hard-cases 52/52, identical on two runs. |

Next decision (owner): accept the two false-unknown rows for now, or read them (spends v2; a v3 is then needed for the claim).
