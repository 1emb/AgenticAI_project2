# Blind classifier acceptance v3

## Summary

Created **600 read-only v3 rows**, specification `2026-11-02c`. Balance adjustment: the current spec has 17 non-unknown labels, so preserving 600 rows and 30 per non-unknown label requires **90 unknown**, rather than the requested 60. The requested counts cannot all hold simultaneously.

Coverage: **79 typo, 60 long, 180 two-task, 185 action-versus-information**. Title and request-order quotas pass. All seven unknown sub-kinds have at least eight rows. Source checks found zero normalized duplicates, shared six-word shingles, or shared family IDs. Details: [acceptance-v3-report.md](/home/sheshnagnobackup/mnguyen/AgenticAI_project2/runs/codex/acceptance-v3-report.md).

SHA-256: `879bd4274376434653f576b44bbfab1d674065b8d8acd2f6fb35688b133ebaf6`.

Only `runs/codex/` was written. All 85 tracked content hashes and post-baseline Git status are unchanged. Nine initial pre-existing modifications became clean externally before baseline capture. No model calls, servers, database writes, or commits were made by this task.

## Balance and specification

The current `intents.py` contains **18 labels total**: 16 ordinary answerable labels, `student_list`, and `unknown`. Thirty rows per non-unknown label produces 510 rows. Adding the requested 60 unknown rows would produce 570, not 600. An asynchronous clarification was sent; no answer arrived before construction. This artifact preserves 600 total and equal 30-row non-unknown counts, using 90 unknown rows. This is an explicit balance deviation, not a claim to satisfy the incompatible 60-unknown allocation. No extra label was invented.

Golds use the current intent descriptions and `CLASSIFY_SYSTEM`, `COUNT_SYSTEM`, and `RESCUE_SYSTEM`. For independent requests, the first supported request supplies the label, regardless of unsupported requests before it. When both are supported, textual order determines the label. When neither is supported, the label is unknown. `student_list` remains a supported classification even though its response refuses the roster. Missing entities and permission restrictions do not determine scope.

The JSONL has exactly the seven requested fields, IDs `acc-v3-001` through `acc-v3-600`, one-line questions and reasons, allowed tags, unique family IDs, and no topic field. Questions were individually authored without model predictions or a question-template generator. The temporary authoring ledger and draft were removed before the final JSONL was written. Public seed catalog information supplied course titles and codes. Synthetic identities and unresolved entities are classifier inputs, not database answer fixtures.

## Counts by label

| Label | Rows |
|---|---:|
| `prerequisites` | 30 |
| `course_info` | 30 |
| `course_offered` | 30 |
| `lecture_options` | 30 |
| `lecture_meeting` | 30 |
| `who_teaches` | 30 |
| `capacity` | 30 |
| `degree_required` | 30 |
| `degree_credits` | 30 |
| `course_in_plan` | 30 |
| `plan_term` | 30 |
| `my_program` | 30 |
| `register_when` | 30 |
| `term_dates` | 30 |
| `current_term` | 30 |
| `person_info` | 30 |
| `student_list` | 30 |
| `unknown` | 90 |
| **Total** | **600** |

## Unknown sub-kinds

Each unknown row has one primary sub-kind in the text-free construction manifest. Two-request rows may span sub-kinds and are counted once. These are audit annotations, not JSONL topics or extra labels.

| Primary sub-kind | Rows |
|---|---:|
| Greeting / nonsense / non-request observations | 12 |
| Add / drop / swap / withdraw operations | 12 |
| Personal records not held | 24 |
| Other offices | 18 |
| Record changes | 8 |
| Course descriptions and program menus | 8 |
| Unrelated tasks | 8 |
| **Total** | **90** |

Personal-record coverage includes holds, grades, GPA, transcripts, audits and remaining credits, waitlists, vacancies and enrollment counts, enrollment verification, own enrollment and timetable, earned credits, and personal eligibility. Other-office coverage includes tuition, balances, installments, refunds, aid, scholarships, parking, housing, dining, IT, instructor office hours, and advising. Personal registration appointments and time tickets use `register_when`, following the carve-out.

## Counts by tag

Tags overlap. Typo cases contain actual spelling errors; title cases explicitly mention course titles, including intentionally misspelled titles.

| Tag | Rows |
|---|---:|
| `action_vs_info` | 185 |
| `authority_claim` | 23 |
| `break_clock` | 21 |
| `contrast_pair` | 0 |
| `crn` | 77 |
| `greeting` | 9 |
| `incidental_person` | 17 |
| `long` | 60 |
| `missing_slot` | 13 |
| `nonexistent` | 13 |
| `own_id` | 19 |
| `ta_student` | 11 |
| `title` | 190 |
| `two_task` | 180 |
| `typo` | 79 |

## Request ordering, length, and title coverage

| Two-request structure | Rows | Required minimum |
|---|---:|---:|
| Unsupported first, supported second | 68 | 60: one third of 180 |
| Supported first, unsupported second | 68 | 60: one third of 180 |
| Both supported; label follows the first | 34 | 20 |
| Neither supported; label unknown | 10 | 10 |
| **Total** | **180** | **90** |

Every non-unknown label has four unsupported-first cases, four supported-first cases, and two cases with different supported intents. Unsupported-first coverage includes record modifications, document operations, translations and other unrelated transformations, enrollment operations, and other-office services. Information followed by actual enrollment execution is covered. The set includes new typo-heavy course-offering inquiries behind irrelevant preambles and multiple explicit registration-ending inquiries.

The 60 long messages have **81–102 words**, under both whitespace and normalized counts. First requests appear at the beginning in 21, in the middle in 19, and near the end in 20. The author reviewed request positions, task independence, typos, and gold meanings. The auditor checks annotation consistency and quotas; it does not interpret natural language independently.

| Course-taking label | Title rows / 30 |
|---|---:|
| `prerequisites` | 24 |
| `course_info` | 24 |
| `course_offered` | 27 |
| `lecture_options` | 27 |
| `who_teaches` | 23 |
| `capacity` | 15 |
| `course_in_plan` | 27 |
| `student_list` | 16 |

Every course-taking label identified by the repository checker exceeds its ten-title minimum.

## Independence and wording self-check

There are **600 families** and **zero shared source family IDs**, checked against both copies of v1 and v2, current development, and original development. Scenario and gold review was performed by the author; no independent agent was used. Specification boundaries remain covered, while prior concrete scenarios and wording were treated as exclusions.

The supplementary [similarity review](acceptance-v3-similarity-review.json) compares all new rows against 1,693 prior v1, v2, current-development, and original-development records. It uses entity-masked token `SequenceMatcher` against same-label records, with a 0.66 candidate threshold. Ten initial candidates were reviewed and rewritten from distinct situations. The final screen has zero candidates. It supplements scenario review and does not prove semantic independence.

The offline [v3 auditor](check_acceptance_v3.py) extracts examples and all three complete prompt constants by AST, without importing registrar modules. Normalization matches the repository checker: Unicode NFKC, case folding, and Unicode alphanumeric tokens. Punctuation, apostrophes, hyphens, and underscores separate words. It checks every sliding six-word window in each question, reason, their concatenation, and serialized record. Exact normalized question reuse is checked separately, including utterances shorter than six words. All 600 questions are unique internally.

JSONL sources contribute question, original-question, and nested paraphrase fields. Wording catalogs contribute lines; Markdown documentation contributes question-table columns. The hard-case table is extracted separately. Unrelated utterances are not concatenated. Schema keys, answer payloads, and evaluation commentary are not student wordings. All source hashes are preserved in [acceptance-v3-validation.json](acceptance-v3-validation.json).

| Source group | Utterances / lines | Shared six-word rows | Normalized duplicate rows |
|---|---:|---:|---:|
| Intent examples | 55 | 0 | 0 |
| Intent descriptions, additional exclusion | 18 | 0 | 0 |
| Full `CLASSIFY_SYSTEM` | 1 | 0 | 0 |
| Full `COUNT_SYSTEM` | 1 | 0 | 0 |
| Full `RESCUE_SYSTEM` | 1 | 0 | 0 |
| v1 under `runs/codex/` | 600 | 0 | 0 |
| v1 tracked copy | 600 | 0 | 0 |
| v2 under `runs/codex/` | 600 | 0 | 0 |
| v2 tracked copy | 600 | 0 | 0 |
| Current development, including spent misses | 253 | 0 | 0 |
| Original development, additional exclusion | 240 | 0 | 0 |
| `hard-cases.jsonl` | 52 | 0 | 0 |
| Hard-case table | 52 | 0 | 0 |
| All `plan.jsonl` entries | 115 | 0 | 0 |
| All `data/testset` wordings | 2,682 | 0 | 0 |
| Phase-2 utterances, additional exclusion | 90 | 0 | 0 |

Groups overlap intentionally and are not independent counts. The test-set scan includes classifier sets, student/professor questions and paraphrases, and wording catalogs.

Negative controls detected exact and partial six-word leaks from all 16 groups, normalization changes, and short exact duplicates. Nine benchmark mutations were rejected: invalid label, obsolete topic field, reused family, normalized duplicate, obsolete spec version, short long-tagged text, missing row, inconsistent task annotation, and invalid tag. Evidence: [acceptance-v3-self-test.json](acceptance-v3-self-test.json).

The tracked checker's offline self-test passed. Its normalization and shingle functions agree with the v3 auditor on all 600 questions and reasons; label and course-taking-label sets also agree. Its pair-audit entry point still assumes v1 IDs/version, and its aggregate count expression has not been adapted to v3. The v3 auditor therefore uses explicit label targets and request-order checks without changing the tracked checker. No grading or pipeline/model evaluation was run.

## Excluded specification gaps and suggested rules

No held-out wording is reproduced here. These scenario types were excluded rather than assigned uncertain golds.

| Excluded scenario type | Specification gap | Suggested rule |
|---|---|---|
| Course-content prose combined with a supported catalog fact | The `course_info` description still sends prose requests to unknown even when a catalog fact follows, conflicting with the new supported-request rule. | Remove that absolute precedence clause; apply the supported-request rule to independent content and metadata requests in either order. |
| Different intent requests about one course, section, or shared subject | `COUNT_SYSTEM` merges facts about one subject, while `CLASSIFY_SYSTEM` describes one task as fields within one intent. A merged unsupported/supported bundle can suppress rescue. | Count independent capability types separately even when they share a subject; keep fields within one intent together. |
| Course meeting inquiry without specifying one section or all choices | `lecture_options` covers alternatives, while `lecture_meeting` permits a missing CRN. | Use `lecture_meeting` for an explicitly single section, even without its CRN; default undifferentiated course-wide choices to `lecture_options`. |
| Course-operator inquiry without a person or academic-unit cue | The target could be the instructor or owning department. | Require an explicit unit cue for `course_info`; otherwise use `who_teaches` for teacher-oriented queries, or clarify when no target is apparent. |

Same-course mixed content/metadata cases were deliberately avoided. Two-supported-request coverage uses different subjects or clearly separate capabilities. Ordinary multi-field requests within one supported intent remain included. The changed classifier rule and the extractor's older first-task wording can also disagree downstream after an unsupported-first message; extraction correctness is outside this classifier-only set.

## Freeze and workspace

The final [classifier-acceptance-v3.jsonl](classifier-acceptance-v3.jsonl) is UTF-8 JSONL with a terminal newline and mode **0444**. The frozen check reads the actual file, verifies that no write permission bits are set, recomputes the full audit, and requires exact agreement with saved validation.

```bash
python -B runs/codex/check_acceptance_v3.py --self-test
python -B runs/codex/check_acceptance_v3.py --frozen
```

| Artifact | SHA-256 |
|---|---|
| `classifier-acceptance-v3.jsonl` | `879bd4274376434653f576b44bbfab1d674065b8d8acd2f6fb35688b133ebaf6` |

| Specification source | SHA-256 |
|---|---|
| `registrar/agent/intents.py` | `97025a8b2389c4da569ff688e164b28d433417f43d119ef40aed48c3b5c03ebe` |
| `registrar/agent/llm.py` | `6cd39c30aca6222fab1281603317e9df5d5201938ef3ac86289a8bdceaa5a7c7` |
| `registrar/agent/programs.py` | `e618f21fd4aae2286563bbfa3237103e8f8d0cccd6770907b83e25a60d0e70f2` |

The [workspace baseline](acceptance-v3-baseline.json) records all 85 tracked file hashes. Initial inspection showed nine pre-existing modifications; an external change made status clean before hash baseline capture. This task issued no tracked-file or Git mutation. Since capture, tracked contents and `git status --short` remain unchanged. Every task write was confined to `runs/codex/`; no database calls or writes, model calls, servers, or commits were made.

The frozen file has not been evaluated against a model. Audit success establishes structure, coverage annotations, and lexical exclusions under the documented 30/90 allocation; it is not a classifier score.
