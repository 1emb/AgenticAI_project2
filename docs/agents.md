# Tool-calling agents (`registrar/agents/`)

Two agents, the Student agent and the Professor agent, answer the questions in `data/testset/` with any
OpenAI-compatible model that supports tool calling (Ollama by default). They sit next to the team's pipeline in
`registrar/agent/` and do not change it. Both are graded with the same contract (`registrar/eval/grader.py`).


## How they work

```text
question -> agent -> ToolLoop -> model
                       ^          | tool calls
                       |          v
                       +- results <- tools -> PostgreSQL
                                     |
            reply + JSON answer <- answer.py (built from tool results)
```

| File | Role |
|---|---|
| `registrar/agents/loop.py` | The loop: model, tools, results, repeat until a plain reply (max 8 steps). Accepts tool calls a local model prints as text |
| `registrar/agents/calendar.py` | The clock and the term rules: current term, "last semester", and "next semester" (the coming term during a break) |
| `registrar/agents/answer.py` | Builds the graded answer: `{allowed: true, ...facts}`, or a refusal with `reason`, `target`, `own_answer` |
| `registrar/agents/student/` | Student tools and prompt |
| `registrar/agents/professor/` | Professor tools (33) and prompt |
| `registrar/eval/runner.py` | Evaluation loop and report for any persona |
| `registrar/eval/known_issues.py` | Test-set wordings no correct agent can pass; reported separately |

Two rules:
- **The model never types the graded answer.** Tools return facts in the test set's answer shapes; Python assembles
  the JSON. Arithmetic, term resolution and permissions are Python.
- **Permissions are enforced by the tools.** No tool reads a phone, date of birth, SSN, GPA, transcript, or another
  instructor's salary or hire date. A refusal's target ID is recorded for grading and never sent to the model.


## Run

Start the database (`./db/start.sh`) and Ollama.

### Running the Student agent

```bash
python scripts/student_agent.py --student 801930214 --verbose
```

| Option | Meaning |
|---|---|
| `--student <id>` | Required. University ID of the logged-in student |
| `--verbose` | Print every tool call and its result |
| `--show-answer` | Print the JSON answer the grader would see after each reply |
| `--as-of <time>` | Set the clock, e.g. `2026-12-20T18:00:00Z` (winter break: "this semester" becomes Spring 2027). Default: now |
| `--model <name>` | Model name, default from `LLM_MODEL` (`qwen3-coder:30b`) |
| `--base-url <url>` | Endpoint, default from `LLM_BASE_URL` (Ollama) |

### Questions to try

| Kind | Example |
|---|---|
| Catalog | What are the prerequisites for CS 5990? · Is CS 4710 offered next spring? · Who teaches CS 2230 this fall? |
| Sections | When does CRN 10011 meet? · What's the capacity of CRN 10001? |
| Degree plan | Is CS 5110 required for my degree? · What's in semester 1 of my plan? |
| Calendar | Which term are we in? · When is the withdrawal deadline this semester? |
| Refused | What's Raj Martinez's email? · List all students in my program. · What's Juan Hall's phone number? |
| Mixed | Who teaches CRN 10011, and what's their phone number? (answers the instructor, refuses the phone) |

---

### Run Profs and others

```bash
./db/start.sh                                                      # Postgres with data/seed loaded
python scripts/professor_agent.py --professor 801408626 --verbose  # chat as Jose Wilson (CS professor)
python scripts/professor_agent.py --professor 800020284 --verbose  # Not working; need to add TA in course. 
python scripts/eval_professor_agent.py --limit 20                  # grade against the test set
python scripts/eval_professor_agent.py --paraphrases               # all 606 wordings
pytest -q                                                          # no model needed
```

Options for the chat scripts: `--as-of 2026-12-20T18:00:00Z` (clock), `--show-answer` (the graded JSON), `--model`,
`--base-url`. The evaluation scripts take `--intent`, `--id`, `--limit`, `--paraphrases`, and write
`runs/<persona>-<model>-<time>.jsonl`.

**Model settings.** `LLM_BASE_URL` and `LLM_MODEL` come from the shell or `.env` (the shell wins). The defaults are
Ollama (`http://127.0.0.1:11434/v1`, `qwen3-coder:30b`). The team's vLLM server needs tool calling enabled
(`--enable-auto-tool-choice` and a `--tool-call-parser` for the model) before these agents can use it.


## Professor agent

**My sections** are the user's `lecture_staff` rows (taught, or assisted as a TA), non-cancelled, current or past.
For a student in one of them the professor or TA sees name, email, program, status and the grade in that section, plus
the section's roster, counts and grade statistics. The student tools check this in the data and record the refusal
themselves when it fails (a student never in the user's sections: `student_record_not_permitted`; a colleague's
section: `student_list_not_permitted` with target `{term, crn}`). The model refuses the rest with `decline_request`.

Which tools use which sections, following the generators:
- instructor of record only: schedule, week, day, section times, load, capacity, course and load history,
  teaching history, course trend, grade submission, my TAs;
- taught or assisted: roster, enrollment counts, student checks, withdrawals, grades, distribution, DFW, incompletes,
  students taught; TA assignments are the assisted ones.

**A CRN with no term.** CRNs restart every term. A named term always wins. Otherwise the tool reads the CRN by what is
asked, and tells the model which term it used:
- times and capacity: this term if it is the user's, else their upcoming section, else this term's section;
- rosters and counts: this term if it is the user's, else their most recent past section, else an upcoming one;
- grades and withdrawals: the user's most recent section with that CRN whose grades were submitted;
- one student's grade: the user's section with that CRN that the student is in.

A course instead of a CRN picks the user's section of it; when they have several, the tool asks which CRN.


## Test and Evaluation 

### Evaluating the student agent

```bash
python scripts/eval_student_agent.py --limit 20                  # quick run
python scripts/eval_student_agent.py                             # all 152 cases
python scripts/eval_student_agent.py --paraphrases               # all 456 wordings
python scripts/eval_student_agent.py --intent access_denied      # one intent (repeatable)
python scripts/eval_student_agent.py --id stu-capacity-002 --verbose
```

Each case runs in a fresh agent set to the case's student and clock. The JSON answer is graded with the contract in
`data/testset/README.md`: `allowed` first, then every ground-truth field; access-control replies are scanned for
`must_not_mention` values. The script prints PASS or FAIL per run, then scores by intent and category, leaks, runs
that hit the step limit, and failed tool calls. Every run is saved to `runs/<model>-<time>.jsonl` with the question,
reply, answer, expected answer and tool calls.


### Tests: Student

```bash
pytest -q          # 192 passed; needs the database, not the model
```

| File | What it checks |
|---|---|
| `tests/test_student_tools.py` | Replays all 152 cases with the tool calls a perfect agent would make and grades them. A failure here is a bug in the code, not the model |
| `tests/test_student_rules.py` | Rules the cases never reach: deadline day, cancelled sections, default terms, phrase resolution at each clock, refusal targets, no private fields in any tool |
| `tests/test_student_agent.py` | The loop with a scripted fake model: answer assembly, refusals, bad tool calls, step limit, refusal targets never sent to the model |
| `tests/test_grader.py` | The grader accepts correct answers and rejects wrong ones |

### Tests: Professor

| File | Checks |
|---|---|
| `tests/test_professor_tools.py` | Replays all 202 cases and every paraphrase with the calls a correct agent makes, and grades them |
| `tests/test_professor_rules.py` | Bare-CRN rules, TA rights, data-driven refusals, privacy of every tool, UTC times, weekdays, deadlines, winter break |
| `tests/test_professor_agent.py` | The loop with a scripted fake model: refusals, partial answers, own salary, leaks, prompt |
| `tests/test_student_*.py`, `tests/test_grader.py` | The Student agent and the grader |

Every professor rule was checked by planting the bug on purpose (counting withdrawn students, removing a permission
check, using ungraded terms, ...) and confirming that a test fails.

The student tests still show 60 failures from the data update of 2026-11-05 (new own-record intents, capacity fields,
TA refusal scenarios); see `data/README.md`, "What changed since your Student Agent".

### Known test-set issues (professor)

Nine of 606 wordings, listed in `registrar/eval/known_issues.py`; the evaluation prints the score with and without them.
- `prof-access_allowed-008` (3 wordings): "Does CS 5410 have prerequisites?" expects `[["CS 3410"]]`, while
  `course_catalog` cases with the same wording expect `[[{"course", "min_grade"}]]`.
- `prof-enrollment_count-005` (2 wordings): a bare CRN that is the user's own section this term, yet the answer is the
  Spring 2027 section.
- `prof-roster-003`, `prof-withdrawals-002`, `prof-withdrawals-004`, `prof-section_grades-002` (one wording each):
  "my COURSE section" when the user had two or three sections of that course; the answer names one.

More broadly, `data/testset/README.md` says a CRN with no term means the current term, but 24 professor cases expect
another term. The rules above recover all of them except `prof-enrollment_count-005`.
