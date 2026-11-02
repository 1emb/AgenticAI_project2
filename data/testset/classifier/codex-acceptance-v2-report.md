# Blind classifier acceptance v2

## Summary

Created [acceptance v2](/home/sheshnagnobackup/mnguyen/AgenticAI_project2/runs/codex/classifier-acceptance-v2.jsonl): **600 rows, 30 per label**, specification `2026-11-02b`. Coverage: 80 typo, 60 long, 108 two-task, and 134 action-versus-information rows. All topic, title, family-separation, duplicate, and shingle checks pass.

The JSONL is read-only. SHA-256: `5306a7c4a71f85275fe9c5324001d118785d58d52e56f3bc5cb70f43a48b356b`.

Only `runs/codex/` was written. Tracked contents and `git status --short` are unchanged. No model calls, servers, or commits.

## Specification and construction

Gold labels and referral topics were assigned against the working-tree `registrar/agent/intents.py` and the complete `CLASSIFY_SYSTEM` in `registrar/agent/llm.py`, using `spec_version: "2026-11-02b"`. The record fields match v1; IDs run from `acc-v2-001` through `acc-v2-600`. The 60 referral records alone contain `expected_topic`, using readable enum keys. Every record has one gold intent, a one-line reason, allowed tags, and a family ID.

The questions were manually authored from new student situations, without a question template generator or model predictions. The author read prior sources for exclusion and family review. Public titles and codes were checked against the local course seed catalogue; no database queries were needed. Names and entity combinations are classifier inputs rather than database answer fixtures. Missing, ambiguous, misspelled, retired, and nonexistent entities retain the requested-task label.

The review covers both task orderings, incidental financial/course/person context, delivery of facts into notes, prerequisite conditions versus individual eligibility, department ownership versus instructor assignment, configured capacity versus current enrollment, and static curriculum requirements versus personal progress. The adopted bare-credit and self-directed course-add defaults are included. Record changes and prose course descriptions use the closed capability policy. No label was changed using model feedback.

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
| `not_in_data` | 30 |
| `outside_registrar` | 30 |
| `unknown` | 30 |
| **Total** | **600** |

## Counts by tag

Tags overlap. Typo rows contain actual spelling errors rather than relying on abbreviations alone. A title tag includes an explicitly named course title, including a misspelled title. Long rows have 80–200 words under both whitespace and normalized token counts.

| Tag | Rows |
|---|---:|
| `action_vs_info` | 134 |
| `authority_claim` | 21 |
| `break_clock` | 22 |
| `contrast_pair` | 12 |
| `crn` | 90 |
| `greeting` | 19 |
| `incidental_person` | 17 |
| `long` | 60 |
| `missing_slot` | 16 |
| `nonexistent` | 16 |
| `own_id` | 20 |
| `ta_student` | 9 |
| `title` | 160 |
| `two_task` | 108 |
| `typo` | 80 |

## Two-task and long-message coverage

| Two-task order | Rows | Share of two-task rows |
|---|---:|---:|
| Information then action | 36 | 33⅓% |
| Action then information | 36 | 33⅓% |
| Information then information | 36 | 33⅓% |
| **Total** | **108** | **100%** |

Action-first coverage comprises 8 enrollment changes, 4 document delivery/issuance requests, 10 outside-service operations, 12 profile changes, and 2 unrelated operations. Information-first rows include 34 enrollment changes requested second and 2 profile changes requested second. These counts concern requested operations; nothing was executed.

Eleven two-task rows use the same verb in both parts. Six reversed-task contrast pairs share their family IDs: four timing/enrollment pairs, one capacity/profile-change pair, and one person/roster pair. The selected gold follows the first independent request, including unavailable requests. Multiple fields within a single intent remain one task.

Long coverage is three rows per label, 60 total, ranging from 89 to 101 whitespace-delimited words. The first request occurs at the beginning in 20, the middle in 21, and near the end in 19. Position, ordering, and action semantics were manually annotated; the checker verifies those annotations and numerical quotas rather than independently understanding prose.

## Course-title coverage

Each course-taking label reaches at least 10 title rows out of 30. As in v1, the quota also applies to capacity and student lists.

| Label | Title rows / 30 |
|---|---:|
| `capacity` | 13 |
| `course_in_plan` | 20 |
| `course_info` | 17 |
| `course_offered` | 20 |
| `lecture_options` | 20 |
| `prerequisites` | 20 |
| `student_list` | 16 |
| `who_teaches` | 16 |

## Referral topics

Every one of the 24 closed topics appears at least twice. Topic golds reflect the first task, even when a later task belongs to another intent or topic.

| Label | Readable topic key | Rows |
|---|---|---:|
| `not_in_data` | GPA | 2 |
| `not_in_data` | add, drop, swap or withdraw for me | 8 |
| `not_in_data` | degree audit or progress | 2 |
| `not_in_data` | enrollment verification | 2 |
| `not_in_data` | grades | 2 |
| `not_in_data` | holds | 2 |
| `not_in_data` | my eligibility or whether I meet the prerequisites | 2 |
| `not_in_data` | my enrollment, schedule, completed courses or earned credits | 2 |
| `not_in_data` | registration appointment or time ticket | 2 |
| `not_in_data` | seats available or enrollment count | 2 |
| `not_in_data` | transcript | 2 |
| `not_in_data` | waitlist | 2 |
| `outside_registrar` | IT account or password | 2 |
| `outside_registrar` | account balance | 3 |
| `outside_registrar` | advising appointment | 3 |
| `outside_registrar` | dining | 2 |
| `outside_registrar` | financial aid | 3 |
| `outside_registrar` | housing | 2 |
| `outside_registrar` | instructor office hours | 3 |
| `outside_registrar` | parking | 2 |
| `outside_registrar` | payment plan | 2 |
| `outside_registrar` | refund | 3 |
| `outside_registrar` | scholarship | 2 |
| `outside_registrar` | tuition | 3 |

## Independence and family review

There are **591 families**, with **zero shared family IDs** against the union of v1 acceptance and current development. Related variants remain together: six two-row reversal families, one three-row joint-supervision family, and one two-row handbook-scan family. The other rows have distinct concrete situations. A family denotes a situation and its related requests; a shared label, entity, missing-slot pattern, or specification boundary alone does not define a family.

The review used the prior family descriptions, prior long scenarios, and an entity-masked similarity screen over all 600 new rows against 846 v1/development rows. Seventeen initial same-label similarity candidates were manually reviewed and rewritten from more specific situations; the final screen has zero candidates at its 0.66 threshold. This screen is supplementary: it does not establish semantic independence. The gold and scenario review was performed by the author, without an independent reviewer. The wording audit proves the stated lexical exclusions, not semantic novelty or classifier accuracy.

Construction annotations contain IDs, labels, families, ordering, and request positions without question text: [acceptance-v2-manifest.json](acceptance-v2-manifest.json). Similarity evidence contains IDs and scores without question text: [acceptance-v2-similarity-review.json](acceptance-v2-similarity-review.json).

## Wording self-check

The updated offline auditor is [check_acceptance_v2.py](check_acceptance_v2.py); its final counts, source hashes, and checks are in [acceptance-v2-validation.json](acceptance-v2-validation.json). It uses AST parsing and standard-library code, without importing or executing registrar modules.

Normalization is Unicode NFKC, case folding, and Unicode alphanumeric word tokens. Apostrophes, underscores, hyphens, and punctuation separate tokens. Every sliding six-word window is checked. It scans each question, reason, their concatenation, and the serialized record. Exact normalized question reuse is checked independently, including utterances shorter than six words. The questions are also unique within v2.

The full AST value of `CLASSIFY_SYSTEM` is one source document, including its quoted examples and continuous rule text. Intent examples are extracted separately. JSONL sources contribute question/paraphrase fields; wording catalogues contribute their lines; other Markdown files contribute their question-table columns. Required schema keys, enum tables, answer payloads, and evaluation commentary are not student wordings. Unrelated source utterances are not concatenated to manufacture cross-example shingles.

| Prohibited/source wording group | Utterances or lines | Shared six-word rows | Normalized duplicate rows |
|---|---:|---:|---:|
| v1 acceptance | 600 | 0 | 0 |
| current development | 246 | 0 | 0 |
| intents.py examples | 61 | 0 | 0 |
| CLASSIFY_SYSTEM rules | 1 | 0 | 0 |
| hard-case table | 52 | 0 | 0 |
| hard-cases.jsonl | 52 | 0 | 0 |
| plan.jsonl | 115 | 0 | 0 |
| data/testset wordings | 2075 | 0 | 0 |
| phase2 utterances | 90 | 0 | 0 |
| original development | 240 | 0 | 0 |

The plan scan includes all 115 entries; the phase-2 scan separately covers 90 utterances. The broader test-set scan includes v1 copies, current classifier development, hard cases, student/professor questions and paraphrases, and wording catalogues. Original Codex development is checked additionally.

Negative controls detected injected exact and partial six-word leaks from all ten source groups, normalization changes, and short exact duplicates. Ten mutations were rejected: invalid label, non-readable topic, reused source family, normalized duplicate, obsolete spec version, unpaired contrast, short long-tagged text, insufficient topic coverage, missing row, and inconsistent two-task annotations. Results are saved in [acceptance-v2-self-test.json](acceptance-v2-self-test.json).

```bash
/home/sheshnagnobackup/mnguyen/envs/registrar/bin/python -B runs/codex/check_acceptance_v2.py --self-test
/home/sheshnagnobackup/mnguyen/envs/registrar/bin/python -B runs/codex/check_acceptance_v2.py --frozen
```

The frozen check reads the actual acceptance file, requires no write permission bits, reruns the complete audit, and requires exact agreement with the saved validation result. It prints counts, hashes, and IDs only.

## Excluded specification gaps

The following ambiguous scenario types were excluded. These are proposed rules for future definitions, not assumptions used to assign v2 golds. No v2 question is reproduced here.

| Excluded scenario type | Unsettled boundary | Suggested rule |
|---|---|---|
| Enrollment procedure guidance without a timing or execution request | The window and execution definitions do not positively cover an open-ended procedural explanation. | Assign pure procedural guidance to `unknown`; use `register_when` for explicit window facts and the action topic for requested execution. |
| A course-only location/time inquiry that does not distinguish one section from all choices | Missing-CRN `lecture_meeting` overlaps a course section-options lookup. | Use `lecture_meeting` when a single section is explicitly targeted; default undifferentiated course meeting inquiries to `lecture_options`. |
| An unqualified course-operator inquiry | The intended answer might be a person or an academic unit. | Default to `who_teaches` unless the request explicitly identifies a department or other academic owner. |
| Joining or leaving a waiting queue | Both the waitlist topic and broad enrollment-action wording can appear relevant. | Use the waitlist topic for queue operations; reserve the registration-action topic for changes to registered sections. |
| Approval of an external transfer equivalency or curriculum substitution | A decision about a new exception can be confused with lookup of an existing plan entry. | Use `unknown` for approval/exception requests; reserve `course_in_plan` for existing stored plan membership, category, or placement. |

## Freeze and workspace

| Artifact | SHA-256 |
|---|---|
| `classifier-acceptance-v2.jsonl` | `5306a7c4a71f85275fe9c5324001d118785d58d52e56f3bc5cb70f43a48b356b` |

The acceptance file is UTF-8 JSONL with a terminal newline and permissions `0444`. This report and validation artifacts were prepared from the final serialized bytes, the temporary authoring source was removed, and the acceptance file was written last. The final frozen verification checks the same bytes. Golds have not been exposed to model predictions.

| Specification source | SHA-256 |
|---|---|
| `registrar/agent/intents.py` | `84afed94a9b33e5b5e0ada9b609f9bd3a14f9218e6722f4fd999e4bd8de17425` |
| `registrar/agent/llm.py` | `cd5e9d88732deeefac1000815446fc13647f41f3cd629d73a8b6f0b4cdfc360f` |
| `registrar/agent/programs.py` | `920fcb537847f0ce5c26aecd9aef135fe1005c54971389a0a1c636f8fbb7389a` |

The [workspace baseline](acceptance-v2-baseline.json) records the initial status and hashes of all 73 tracked files. Their contents are unchanged, and final `git status --short` equals the initial output. Existing user modifications and untracked paths were left in place. Every task write is under `runs/codex/`; no database writes, model calls, server starts, or commits occurred.

No classifier score is claimed. Keep the new wording blind during definition tuning. Evaluate only after definitions and runtime settings are frozen, with the existing two-run acceptance criterion and separate topic scoring. Reading misses to change definitions spends this acceptance version.
