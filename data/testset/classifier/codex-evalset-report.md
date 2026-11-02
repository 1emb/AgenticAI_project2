# Classifier evaluation sets

## Summary

Created 240 development cases (12 per label) and 600 frozen acceptance cases (30 per label). All coverage, family separation, and wording overlap checks pass.

Hashes and two excluded specification gaps are documented in [evalset-report.md](/home/sheshnagnobackup/mnguyen/AgenticAI_project2/runs/codex/evalset-report.md). Only `runs/codex/` was written; `git status --short` is unchanged. Concurrent tracked edits are recorded below. No model calls, server starts, or commits were made.

## Specification and construction

Every record uses `spec_version: "2026-11-02"` and `expected_intent`, with exactly one gold label and one-line rationale assigned before any model execution. The working-tree `intents.py`, `CLASSIFY_SYSTEM` in `llm.py`, and the implemented programs are the authority. First independent request in textual order wins. Unqualified named-course taking/registration uses `course_offered`. Capability limits and the closed referral topics are positive definitions; greetings and requests fitting none of them use `unknown`. No label depends on the clock. Untimed break registration retains the documented `current.sequence + 1` rule.

Questions were manually authored from student activities and administrative needs, including community projects, work and transport arrangements, application paperwork, curriculum planning, and campus services. Short fragments, corrections, direct commands, polite requests, anxious explanations, and longer narratives are mixed. No generator template or old case was used to produce new rows. Existing examples and prior runs were read for the required exclusion audit, so this is not a claim that the author was blind to earlier material. Lexical checks cannot prove semantic independence or gold-label correctness; no independent owner review has been performed in this session.

Development has 229 scenario families; acceptance has 556. A family means a concrete situation and its related contrasts, not an intent or a shared entity alone. Related variants stay together, including variants whose selected labels differ. There are zero shared family IDs, zero normalized duplicate questions, and zero shared six-word question shingles between files. The family manifest contains only IDs and labels, without acceptance wording. The split was also reviewed for reused narrative contexts; some development situations were changed before freezing to keep distinct contexts.

Public course codes/titles, term names, and instructor names/ranks were read using `./db/psql.sh` inside `BEGIN READ ONLY`. No private field values were queried. The cases are classifier inputs, not validated database answer fixtures: unknown, ambiguous, missing, and misspelled entities deliberately retain their requested-task labels. Course/CRN/term combinations need not exist. No database writes occurred.

## Counts by label

| Label | Development | Acceptance |
|---|---:|---:|
| `prerequisites` | 12 | 30 |
| `course_info` | 12 | 30 |
| `course_offered` | 12 | 30 |
| `lecture_options` | 12 | 30 |
| `lecture_meeting` | 12 | 30 |
| `who_teaches` | 12 | 30 |
| `capacity` | 12 | 30 |
| `degree_required` | 12 | 30 |
| `degree_credits` | 12 | 30 |
| `course_in_plan` | 12 | 30 |
| `plan_term` | 12 | 30 |
| `my_program` | 12 | 30 |
| `register_when` | 12 | 30 |
| `term_dates` | 12 | 30 |
| `current_term` | 12 | 30 |
| `person_info` | 12 | 30 |
| `student_list` | 12 | 30 |
| `not_in_data` | 12 | 30 |
| `outside_registrar` | 12 | 30 |
| `unknown` | 12 | 30 |
| **Total** | **240** | **600** |

## Counts by tag

Tags overlap. Typo includes realistic abbreviation and informal spelling; a title tag means the question names a course by title, including shortened or misspelled titles.

| Tag | Development | Acceptance | Acceptance target |
|---|---:|---:|---:|
| `action_vs_info` | 25 | 109 | at least 60 |
| `authority_claim` | 4 | 10 | present |
| `break_clock` | 6 | 19 | present |
| `contrast_pair` | 10 | 43 | present |
| `crn` | 30 | 83 | present |
| `greeting` | 4 | 13 | present |
| `incidental_person` | 10 | 30 | present |
| `long` | 8 | 60 | at least 60 |
| `missing_slot` | 12 | 28 | present |
| `nonexistent` | 11 | 18 | present |
| `own_id` | 18 | 33 | present |
| `ta_student` | 4 | 11 | present |
| `title` | 46 | 111 | present |
| `two_task` | 22 | 60 | at least 60 |
| `typo` | 37 | 73 | at least 60 |

The 60 acceptance long messages contain 88–103 whitespace-delimited words each. Their main requests were authored and manually checked at the beginning (20), in the middle (20), and near the end (20). The script verifies length, not linguistic request position. Development long messages contain 89–98 words. Two-task tags mean independent requests, rather than two fields of one intent. Action-versus-information tags cover offerings, windows, academic deadlines, prerequisite rules, curriculum membership, static capacities, personal eligibility/progress, and actual registration changes.

Financial background occurs in registrar-hold and supported-information requests; named courses occur as funding context; named professors occur as background to supported facts and as office-hours context. Those mentions do not override the requested service.

## Course-title coverage

Every course-taking label with a course-mention slot reaches one third by title. The check also applies the threshold to capacity and student lists, even though many of their other rows identify a section or a group. Single-CRN meeting queries are not a course-taking label; some still include a contextual title.

| Label | Development title rows / 12 | Acceptance title rows / 30 |
|---|---:|---:|
| `capacity` | 5 | 12 |
| `course_in_plan` | 5 | 12 |
| `course_info` | 6 | 12 |
| `course_offered` | 6 | 12 |
| `lecture_options` | 6 | 12 |
| `prerequisites` | 6 | 12 |
| `student_list` | 4 | 13 |
| `who_teaches` | 6 | 11 |

## Closed referral topics

Both files cover all twelve topics of each referral label. Acceptance covers each at least twice. Topic golds use the readable enum keys, not the internal codes; no other label has `expected_topic`. Registration actions cover adding/registering, dropping, swapping, and withdrawal. Transcript and enrollment-verification cases include document delivery.

| Label | Readable topic | Development | Acceptance |
|---|---|---:|---:|
| `not_in_data` | GPA | 1 | 2 |
| `not_in_data` | add, drop, swap or withdraw for me | 1 | 5 |
| `not_in_data` | degree audit or progress | 1 | 2 |
| `not_in_data` | enrollment verification | 1 | 2 |
| `not_in_data` | grades | 1 | 2 |
| `not_in_data` | holds | 1 | 2 |
| `not_in_data` | my eligibility or whether I meet the prerequisites | 1 | 3 |
| `not_in_data` | my enrollment, schedule, completed courses or earned credits | 1 | 3 |
| `not_in_data` | registration appointment or time ticket | 1 | 2 |
| `not_in_data` | seats available or enrollment count | 1 | 3 |
| `not_in_data` | transcript | 1 | 2 |
| `not_in_data` | waitlist | 1 | 2 |
| `outside_registrar` | IT account or password | 1 | 2 |
| `outside_registrar` | account balance | 1 | 3 |
| `outside_registrar` | advising appointment | 1 | 3 |
| `outside_registrar` | dining | 1 | 2 |
| `outside_registrar` | financial aid | 1 | 3 |
| `outside_registrar` | housing | 1 | 2 |
| `outside_registrar` | instructor office hours | 1 | 3 |
| `outside_registrar` | parking | 1 | 2 |
| `outside_registrar` | payment plan | 1 | 3 |
| `outside_registrar` | refund | 1 | 3 |
| `outside_registrar` | scholarship | 1 | 2 |
| `outside_registrar` | tuition | 1 | 2 |

## Excluded specification gaps

These are discarded utterances, absent from both files. They were not given speculative gold labels. The suggestions below are proposed additional rules, not rules silently used by this benchmark.

| Excluded question | Unsettled interpretation | Suggested rule |
|---|---|---|
| “Can I add Robotics?” | The unqualified course default explicitly names taking/registering; this self-directed “add” has no timing cue and does not explicitly ask the assistant to perform enrollment. | Extend the unqualified named-course default to self-directed “can I add” (`course_offered`); retain `term_dates` for explicit add timing and `not_in_data` for assistant-executed changes. |
| “How many credits do I need?” | No cue selects the program requirement versus credits personally remaining. | Default the bare credit-need question to the program requirement (`degree_credits`); require explicit earned/remaining/completion language for personal-progress topics. |

All included rows have enough task cues under the supplied rules. Unsupported all-program inventories, prose course descriptions, grade scales, and other unlisted services use the explicit `unknown` inventory policy rather than an invented referral topic.

## Wording and schema self-check

The executable check is [check_evalsets.py](check_evalsets.py); detailed machine-readable counts are in [evalset-validation.json](evalset-validation.json). It parses source with `ast` rather than importing the registrar. Normalization is Unicode NFKC plus case folding, followed by Unicode alphanumeric word tokens; punctuation, underscores, hyphens, and apostrophes separate words. Every sliding six-word window is compared. Questions, reasons, their concatenation, and complete serialized JSON records are scanned. Source utterances are indexed separately, without manufacturing shingles across example boundaries.

| Prohibited source | Source utterances/lines | Development rows with a shared six-word shingle | Acceptance rows with a shared six-word shingle |
|---|---:|---:|---:|
| intents.py examples | 61 | 0 | 0 |
| design-review hard-case table | 52 | 0 | 0 |
| plan.jsonl | 115 | 0 | 0 |
| data/testset wordings | 1140 | 0 | 0 |

The plan check covers all 115 rows, including all 90 phase-2 student questions. The additional test-set scan covers question/paraphrase fields in JSONL files and the wording catalogs in `questions.md`. Reuse found during drafting was rewritten before freezing, without any model feedback. Exact normalized duplicate questions are absent within either file and across files. Deliberate contrast variants within a file may share wording.

The checker validates the exact record fields, IDs, 20 allowed labels, enum keys, spec version, one-line prose, unique IDs and questions, allowed tags, paired contrast families, per-label balance, long lengths, title quotas, referral topic quotas, acceptance coverage minima, family separation, and repository status. Negative controls verified that known leaks from each source class are detected, punctuation/case normalization works, and invalid labels/topics fail.

Run with the specified environment:

```bash
/home/sheshnagnobackup/mnguyen/envs/registrar/bin/python -B runs/codex/check_evalsets.py --self-test
/home/sheshnagnobackup/mnguyen/envs/registrar/bin/python -B runs/codex/check_evalsets.py --no-write
```

The final `--no-write` run rechecks the actual files and requires an exact match with the saved validation results. Its output contains counts and errors by ID, without held-out questions.

## Freeze hashes

| File | SHA-256 |
|---|---|
| `classifier-dev.jsonl` | `773ae2cff760b5992fa5accc27988d0bb34b6671714fe8f2664d8edce6950617` |
| `classifier-acceptance.jsonl` | `39c6a6c9ff1db49789e1b0194b57ddf959bdf7004949564f8bfa0a21225cad4b` |

Both files are UTF-8 JSONL with a trailing newline. Development was finalized first. Validation metadata, the family manifest, checksums, and this report were prepared from the final serialized bytes; acceptance was then written last and made read-only. Its temporary authoring source was removed before that final write. No acceptance question is quoted in this report. Gold answers have never been changed in response to a prediction. Treat future policy changes as a new benchmark version and preserve this hash.

| Specification source at freeze | SHA-256 |
|---|---|
| `registrar/agent/intents.py` | `dd1c136d0b571ec718b5351a24a851846e9e28c3a25f21248ee69d99b39d0bdb` |
| `registrar/agent/llm.py` | `4c02f39722472e9819f365dc551c153951c14aea305133119cca06aba9636591` |
| `registrar/agent/programs.py` | `920fcb537847f0ce5c26aecd9aef135fe1005c54971389a0a1c636f8fbb7389a` |

## Workspace and execution record

All writes by this task are under `runs/codex/`. The initial tracked-content/status snapshot is retained in `evalset-baseline.json`. Concurrent edits changed tracked bytes while this work was underway, including specification files, but the final `git status --short` equals the starting value. The following observed concurrent paths are recorded in `evalset-source-review.json`:

- `README.md`
- `data/testset/README.md`
- `registrar/agent/intents.py`
- `registrar/agent/llm.py`
- `registrar/chatlog.py`
- `registrar/ui/static/index.html`
- `scripts/grade.py`
- `scripts/review.py`

The current `intents.py`, `CLASSIFY_SYSTEM`, and `programs.py` were re-read after detecting that drift. The twenty label names, closed topic enums, and classification policy remain compatible with all golds. The person/list descriptions gained explicit field/individual wording, and referral-topic gloss/selection support was added. No gold label needed a change. The final source hashes above identify the reviewed versions; the original baseline was not overwritten. This record does not claim that all tracked bytes stayed unchanged. No tracked file was written or reverted by this task.

No model call, model scoring run, server start, or commit occurred. All validation was offline except the read-only public-entity database queries. The 156-case result and earlier hard-case score were supplied by the user and were not rerun.

## Acceptance use

Keep acceptance wording away from definition tuning. After the implementer freezes definitions and settings, run the same acceptance hash twice without intervention, using classifier-only grading and `--confusion`. Each run must reach at least 588/600 overall and 29/30 for every label, with zero answerable selected-primary requests routed to referral/unknown. Report full confusion matrices, per-label precision/recall, errors by tag, false referrals, and differing predictions between runs. Topic golds are provided for a separate topic-selection evaluation; they do not add an extraction/database dependency to the classifier score. No classifier accuracy is claimed by this report.
