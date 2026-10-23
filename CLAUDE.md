# BI Agent MVP — guidance for Claude

A natural-language BI agent: users ask questions in plain English and get a grounded answer, the SQL, a table and a chart. Built in small, verified milestones (M1–M27). `README.md` covers setup and usage; this file covers how to work on the code.

## Keep the docs current

- `docs/build-plan.html` is the living plan: roadmap, step-by-step milestone guides, development log, known limits. Update it whenever the plan changes, a milestone starts or finishes, a decision is made, or a new limit appears. Keep the "Last updated" line and the development log current, and label results as **seen** (output observed) or **reported** (the owner said so).
- Edit it in place; git keeps history. Never create new `_vN` copies. The older `docs/BI Agent MVP_ incremental build plan*.html` files are historical only.
- Update `README.md` when setup steps, configuration, API routes, roles or user-visible behavior change. Its **Features** section is the canonical list of what the project offers: add to it whenever a feature lands.
- Update this file when conventions, layout or status change.

## Test-driven development (always)

Every change to behaviour follows red, green, refactor:

1. **Red:** write or update the test first. Run it and confirm it fails, and fails for the expected reason (not a typo or import error in the test itself, unless the module genuinely doesn't exist yet).
2. **Green:** write the smallest code change that makes it pass. Run the full suite, not just the new test.
3. **Refactor:** tidy up only while every test stays green.

- A bug fix starts with a test that reproduces the bug.
- Show the owner both runs: the failing output and the passing output.
- Never weaken, skip or delete a test to make it pass. If a test is wrong, say why before changing it.
- Exempt: documentation-only changes and configuration with no behaviour. Scratch experiments may skip TDD but are never committed without tests.

## Working rules

- One milestone at a time: explain why, make the smallest change, run the tests, then stop and wait for the owner's approval before starting the next milestone.
- Never claim a test passed unless its output was observed. Say "expected" otherwise.
- Diagnose from real error output before changing code. Never edit a failing test to make it pass; find out why behavior changed.
- Add a dependency only when the current milestone needs it.
- The LLM never enforces authorization. Generated SQL never runs without the validator and the role's read-only database login.
- Secrets stay out of source. `.env` is git-ignored. `docker compose config` prints real secrets — never paste its output. Never print tokens or passwords.
- Before every commit, check `git status` for `.env`, `.venv`, `__pycache__`, `.DS_Store`. One commit per milestone or sub-milestone, conventional messages (`feat:`, `fix:`, `test:`, `refactor:`, `chore:`, `docs:`).
- The owner is learning as they build: explain decisions briefly, give exact commands for macOS/zsh, and say what output to expect.

## Commands

```bash
docker compose up --build -d                      # backend :8000, frontend :8501, db host :5433
docker compose exec backend python -m app.cli create-user <name> <analyst|limited>
cd backend  && .venv/bin/python -m pytest         # integration tests need the db container
cd backend  && .venv/bin/python -m pytest -m "not integration"
cd frontend && .venv/bin/python -m pytest
docker compose exec -T db psql -U admin -d postgres < db/init/<file>.sql   # apply new init SQL to a running db
cd backend && set -a && source ../.env && set +a && .venv/bin/python -m evals.run [--repeat 3] [--case ID]   # real-model evaluation (costs tokens on OpenRouter)
cd backend && LLM_PROVIDER=ollama LLM_TIMEOUT_SECONDS=120 .venv/bin/python -m evals.run --repeat 3   # same, on the local model (free; about 4 minutes)
cd backend && .venv/bin/python -m retail.load --scale full   # rebuild the retail demo database (~20 s; scales: tiny, small, full)
```

Code changes need `--build`; `.env` or compose environment changes need the container recreated.

## Architecture

- Logs are one JSON object per line: log with a short message and `extra={...}` fields (`request_id`, `username`, ...), not formatted strings, for anything worth searching.
- `backend/catalog/*.toml` (one file per business area, plus `metrics.toml`): descriptions, grain, caveats, allowed values, units and `pii` flags for every retail table and column. `app/catalog.py`: strict `load()`, `introspect(run)` (types, keys, relationships, row counts from the database, through any `run(sql, params)` function, so it never imports the driver) and `drift()`. Tests fail if the catalog and the database disagree, or if `pii` flags differ from what `grants.sql` withholds from analysts. Describe every new column there.
- `backend/policy/guardrails.toml`: the guardrail policy (SQL limits, function allowlist, blocked prefixes, roles with tables and login variable). `app/policy.py` loads and strictly validates it at import, so a malformed file stops the backend (fail closed); `access.py`, `limits.py` and `sql_guard.py` read it. Edit rules there, not in Python. Environment variables may only lower its limits.
- `backend/app/main.py`: routes, exception handlers (each maps to a generic client message; details go to logs with the request ID), request-ID middleware, `make_generate` (token budget + logging around every LLM call), `conv_key`.
- `auth.py` (argon2, JWT HS256, `current_user`), `appdb.py` (users table in `appdb`), `cli.py` (create-user), `access.py` (`ROLE_TABLES`, `ROLE_DB_ENV`, `AccessError`).
- `db.py`: `run_readonly(sql, params, max_rows, timeout_ms, role)` — the role picks the database login; read-only transaction, statement timeout, row and byte caps, read through a server-side cursor in batches (limits from `limits.py`, environment `SQL_MAX_ROWS`, `SQL_MAX_RESULT_BYTES`, `SQL_TIMEOUT_MS`). It accepts only `ValidatedSQL` (from `validate_sql`) or `TrustedSQL` (fixed code-authored text, never model or user text), both in `sqltypes.py`; anything else raises `UnvalidatedSQLError`.
- `llm/`: `LLMService` interface, `openrouter.py` (any OpenAI-compatible chat API; OpenRouter by default, or Ollama with `LLM_PROVIDER=ollama`, `OLLAMA_BASE_URL`, `OLLAMA_MODEL`), `fake.py`, `budget.py`, typed errors (timeout, rate limit, config, generic).
- `bi/`: `metrics.py` (governed metrics + deterministic builder), `schema.py` (per-role schema text), `text_to_sql.py` (prompt + extraction), `sql_guard.py` (sqlglot validator), `service.py` (LangGraph graph: rewrite → write_sql → declined, or check_sql → execute → explain → ground, or no_rows), `grounding.py`, `rewrite.py`, `chart.py`, `conversation.py`.
- `backend/evals/`: `cases.json` (23 questions with reference SQL and expected rows, or forbidden values for safety cases) and `harness.py` (`run_case` runs a case through the real workflow; expected rows come from running the case's `reference_sql` on the current data, while the stored `expected` rows are the seed-data answer used only by `test_evals.py`; safety cases list `forbidden_tables`; scoring ignores column order and names, matches numbers to 2 decimals). Not shipped in the Docker image.
- `frontend/app.py`: Streamlit sign-in gate, sidebar, welcome screen, chat and answer cards (headline, big-number card, Chart/Table/SQL tabs). `charts.py`: Plotly figure from the backend's chart spec (the backend still picks bar or line). `presentation.py`: labels, number formats, single-value card, declined/no-data detection, `status_for(BackendError)`. `.streamlit/config.toml`: theme, usage statistics off. `client.py`: `post_json`/`get_json`/`login`, raises `BackendError` with the backend's message and status.
- Frontend tests: `tests/test_app.py` drives the real `app.py` with Streamlit's `AppTest`, replacing `client.login` and `client.post_json`; so `app.py` must call them as `client.post_json(...)`, not via `from client import post_json`. Give every chart a unique `key` (history can repeat a figure), and escape `$` in markdown (Streamlit treats `$...$` as maths). Use `width="stretch"`, not the deprecated `use_container_width`.
- `db/init/`: `01_schema`, `02_seed`, `03_roles` (bi_readonly), `04_limited_role` (bi_limited), `05_app_db` (appdb, app_rw, users), `06_audit` (audit.events, insert-only for app_rw), `07_retail` (databases `retail` and `retail_test`, logins `retail_owner`, `retail_analyst`, `retail_limited`, `retail_manager`). Run only on an empty volume.
- `db/retail/`: `schema.sql` (29 tables, keys, checks), `constraints.sql` (foreign keys and indexes, added after loading), `grants.sql` (per-login reads, column-level for personal data and salary). Applied by the loader, not at database start.
- `backend/retail/`: `generate.py` (seeded generator for the fictional Trailhead Outfitters retailer; `generate()` yields batches, `collect()` gathers them; planted stories documented in the module docstring) and `load.py` (`load(url, seed, scale)`, CLI). Not shipped in the Docker image.

## Decisions to preserve

- Defense in depth for SQL: prompt shows only the role's tables → validator (one SELECT or set operation of SELECTs; no write, command or `INTO` node anywhere, including CTEs; no locking; allowed tables; no schema-qualified tables or functions; **functions only from the allowlist** in `sql_guard.py`, never a blocklist; every join linked by a condition unless one side is a one-row aggregate; at most `SQL_MAX_TABLES` tables and `SQL_MAX_DEPTH` nesting) → per-role read-only login. `SQLRejected.user_message`, when set, is the only rejection text shown to users. The database role is the real enforcement.
- Widening the SQL function allowlist is a security change: add an acceptance test and run the real-model evaluation.
- Roles: `analyst` → `orders`, `regions`; `limited` → `regions`. The role comes from the users table on every request, never from the token's claims. Unknown roles raise `AccessError` (403), never fall back.
- Every number in a model-written answer must appear in the result or question; otherwise use the plain fallback. One-row results containing NULL count as no data. Totals and percentages belong in deterministic code.
- Charts come from `bi/chart.py` rules: the spec has the suggested `type`, the `options` that fit (suggestion first) and the column roles (`x`, `y`, `series`, `values`, `size`, `location`, `start`, `end`). The frontend draws only offered types (Plotly, `frontend/charts.py`) and lets the user switch between them. The model never picks a chart. Funnel needs a stage-like label column; shapes are recognised in any column order.
- Conversations are in memory, capped, keyed `username:conversation_id`; another user's ID returns 404, not 403.
- The Streamlit token lives only in server-side session state; refresh signs the user out.

## Testing conventions

- `tests/conftest.py` sets local database URLs and `JWT_SECRET`, and signs every test in as `test-analyst` by overriding `current_user`. Auth tests remove the override to test the real check.
- `tests/routed_llm.py` is the scripted model: it answers by prompt type (`Rewrite…` → rewrite, `You write PostgreSQL…` → SQL, else → answer). Keep those prompt openings stable or update `RoutedLLM`.
- Tests that call `run_readonly` directly to test the database layer wrap their SQL in `TrustedSQL`. `tests/test_execution_path.py` lists the public routes; every other route must depend on `signed_in`.
- Mark tests that need the database `@pytest.mark.integration`. Stand-ins for `generate_sql`/`run_readonly` accept `**kw`.
- Run the real-model evaluation (`evals.run`) after any change to prompts, the model, the validator, the workflow graph or the dataset, and before accepting a new baseline. It exits 1 on any safety failure, data change or regression against the model's own baseline (`evals/baselines/<model>.json`), and 2 if any case could not be scored because the provider failed (such a run never updates the baseline). Reports go to `evals/reports/` (git-ignored).
- Prompt changes can make the model over-refuse. After editing `build_prompt`, run the real-model evaluation; the decline wording must state what always gets a query before saying when to decline.
- Golden numbers from the seed: completed revenue 1,380 total; 570 August, 810 September; September by region North 270, South 300, West 240; August North 250, South 200, West 120.

## Gotchas already hit

- Docker Compose gives shell variables priority over `.env`. If `.env` was loaded with `set -a; source .env` before starting a session, a changed `.env` value is ignored; start Compose with `env -u NAME docker compose up -d` or a fresh terminal.
- Before appending to `.env`, make sure it ends with a newline, or the new line is glued onto the last variable (it once corrupted `JWT_SECRET`). Back it up first and never print its contents.

- Postgres evaluates constant expressions such as `1 / 0` while planning, even inside `CASE`; a test that needs an error on a later row must make it depend on the row (`1 / (g - g)`).
- New limits are read in `app/limits.py`; add each one to `docker-compose.yml` too, or a value in `.env` never reaches the container.

- The retail analyst login has column-level grants, so `SELECT *` on `customers`, `customer_addresses` or `employees` is refused by the database. Prompts and the catalog must list allowed columns only.
- Retail integration tests rebuild `retail_test` only; never point tests at `retail`.

- Inside Compose, use service names (`http://backend:8000`, `db:5432`); host port 5433 exists only outside Docker.
- A missing `environment:` entry (e.g. `BACKEND_URL` on the frontend) silently falls back to `localhost`.
- Each `.gitignore` entry needs its own line.

## Status

M1–M22 committed (last checked: backend 129 passed, frontend 8 passed). M23a (audit trail: `app/audit.py`, `signed_in` dependency, `audit_event` calls; tests use the `audit_events` fixture instead of the database) is committed. M23b (login throttling: `app/throttle.py`, in-memory per username, 5 failures in 15 min lock for 15 min; tests get a fresh throttle via the `fresh_login_throttle` fixture) is committed, 140 backend tests passing. M23c (JSON logs via `app/logging_setup.py`, `LOG_FORMAT=json|text`; public `GET /ready` checks both databases) is committed, 144 backend tests passing. M23 is complete. M24a (dataset and harness) is committed. M24b (`evals/run.py`, real-model runner, and the baseline, now in `evals/baselines/`) is committed; 200 backend tests passing; baseline 20/20 scored cases, 3 of 3 each, with `non-data-hello` as the tracked known gap. M24 is complete. The `NO_QUERY` fix (prompt asks the model to answer exactly `NO_QUERY` for greetings, small talk and change requests; `is_no_query` in `text_to_sql.py`; `declined` node in the graph; `no_query` eval kind) is built, 214 backend tests passing, evaluation 23/23 scored cases 3 of 3 each, saved as the baseline; committed. The code is pushed to a private GitHub repository (`origin`). M25 (production images: lock files, multi-stage, uid 10001, read-only root, docs off by default, Trivy scan; image checks in `image_tests/`) is planned in `docs/build-plan.html` but paused. Phase 7 demo track comes first: M28 is complete (retail dataset: `db/retail/`, `backend/retail/`, `db/init/07_retail.sql`; backend 332 tests passing). Guardrails: full assessment, 26-guardrail specification, roadmap and test matrix in `docs/guardrails.html` (supersedes the G1–G6 draft). GR-SQL-01 (validator allowlist), GR-SQL-06 (one execution path), GR-SQL-04 (bounded result reading), GR-SQL-02 (structure limits), GR-POL-01 (policy file) and GR-POL-02 (prompt rules from the policy) are done: 536 backend tests passing; local-model evaluation 23/23. OpenRouter is out of free credit, so development uses a local model (`LLM_PROVIDER=ollama`, `qwen2.5-coder:7b`); re-run GR-POL-02's evaluation on Qwen 32B when OpenRouter works again. Next: milestone F (demo-ready frontend, planned in the build plan), then GR-SQL-03 (cost check) and GR-WF-01 (one bounded retry). Keep `docs/guardrails.html` current as guardrails land, like the build plan. Phase 7 parts: M28 retail dataset (generated, separate `retail` database), M29 data catalog (TOML files in `catalog/` plus database introspection), M30 retrieval over the catalog (OpenRouter embeddings, pgvector), M31 memory (persistent conversations, verified examples, user facts), M32 demo polish. Open suggestion not applied: converting midnight timestamps to dates for chart labels.
