# Advising agent

Multi-term course planning for the registrar system. An ASP solver (clingo) builds the plan from the student's
record, the degree plan and the course offerings; plain Python re-checks it; an optional LLM only rewrites the
explanation. The agent only reads data.

- Interface and design (inputs from the Router, Data agent and Policy agent; output to the Router):
  [docs/interface.html](docs/interface.html). The typed version is `contracts.py`.
- System design pages: `docs/design/registrar_mindmap.html`, `docs/design/registrar_process_flow.html`.

```bash
pip install clingo pytest
python -m advising_agent.run_example adv-001   # from the repo root
pytest advising_agent/tests -q
```

Until the seed data and the `enrollment` table exist, everything runs on `fixtures/example_db.json`, which uses the
row shapes of the 12 tables plus the proposed `enrollment` table. To use the real database, implement
`contracts.DataTools` with the SQL sketched in `docs/interface.html` section 4.
