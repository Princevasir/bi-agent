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
cd backend && set -a && source ../.env && set +a && .venv/bin/python -m evals.run [--repeat 3] [--case ID]   # real-model evaluation (costs tokens)
cd backend && .venv/bin/python -m retail.load --scale full   # rebuild the retail demo database (~20 s; scales: tiny, small, full)
```

Code changes need `--build`; `.env` or compose environment changes need the container recreated.

## Architecture

- Logs are one JSON object per line: log with a short message and `extra={...}` fields (`request_id`, `username`, ...), not formatted strings, for anything worth searching.
- `backend/app/main.py`: routes, exception handlers (each maps to a generic client message; details go to logs with the request ID), request-ID middleware, `make_generate` (token budget + logging around every LLM call), `conv_key`.
- `auth.py` (argon2, JWT HS256, `current_user`), `appdb.py` (users table in `appdb`), `cli.py` (create-user), `access.py` (`ROLE_TABLES`, `ROLE_DB_ENV`, `AccessError`).
- `db.py`: `run_readonly(sql, params, max_rows, timeout_ms, role)` — the role picks the database login; read-only transaction, statement timeout, row cap.
- `llm/`: `LLMService` interface, `openrouter.py`, `fake.py`, `budget.py`, typed errors (timeout, rate limit, config, generic).
- `bi/`: `metrics.py` (governed metrics + deterministic builder), `schema.py` (per-role schema text), `text_to_sql.py` (prompt + extraction), `sql_guard.py` (sqlglot validator), `service.py` (LangGraph graph: rewrite → write_sql → declined, or check_sql → execute → explain → ground, or no_rows), `grounding.py`, `rewrite.py`, `chart.py`, `conversation.py`.
- `backend/evals/`: `cases.json` (23 questions with reference SQL and expected rows, or forbidden values for safety cases) and `harness.py` (`run_case` runs a case through the real workflow; expected rows come from running the case's `reference_sql` on the current data, while the stored `expected` rows are the seed-data answer used only by `test_evals.py`; safety cases list `forbidden_tables`; scoring ignores column order and names, matches numbers to 2 decimals). Not shipped in the Docker image.
- `frontend/app.py`: Streamlit sign-in gate, chat, table, chart. `client.py`: `post_json`/`get_json`/`login`, raises `BackendError` with the backend's message and status.
- `db/init/`: `01_schema`, `02_seed`, `03_roles` (bi_readonly), `04_limited_role` (bi_limited), `05_app_db` (appdb, app_rw, users), `06_audit` (audit.events, insert-only for app_rw), `07_retail` (databases `retail` and `retail_test`, logins `retail_owner`, `retail_analyst`, `retail_limited`, `retail_manager`). Run only on an empty volume.
- `db/retail/`: `schema.sql` (29 tables, keys, checks), `constraints.sql` (foreign keys and indexes, added after loading), `grants.sql` (per-login reads, column-level for personal data and salary). Applied by the loader, not at database start.
- `backend/retail/`: `generate.py` (seeded generator for the fictional Trailhead Outfitters retailer; `generate()` yields batches, `collect()` gathers them; planted stories documented in the module docstring) and `load.py` (`load(url, seed, scale)`, CLI). Not shipped in the Docker image.

## Decisions to preserve

- Defense in depth for SQL: prompt shows only the role's tables → validator (one SELECT, allowed tables, no schema-qualified names, no `pg_*`/`dblink`/`set_config` functions, no `INTO` or locking) → per-role read-only login. The database role is the real enforcement.
- Roles: `analyst` → `orders`, `regions`; `limited` → `regions`. The role comes from the users table on every request, never from the token's claims. Unknown roles raise `AccessError` (403), never fall back.
- Every number in a model-written answer must appear in the result or question; otherwise use the plain fallback. One-row results containing NULL count as no data. Totals and percentages belong in deterministic code.
- Charts come from `bi/chart.py` rules; the frontend only maps `bar`/`line` to built-in Streamlit charts.
- Conversations are in memory, capped, keyed `username:conversation_id`; another user's ID returns 404, not 403.
- The Streamlit token lives only in server-side session state; refresh signs the user out.

## Testing conventions

- `tests/conftest.py` sets local database URLs and `JWT_SECRET`, and signs every test in as `test-analyst` by overriding `current_user`. Auth tests remove the override to test the real check.
- `tests/routed_llm.py` is the scripted model: it answers by prompt type (`Rewrite…` → rewrite, `You write PostgreSQL…` → SQL, else → answer). Keep those prompt openings stable or update `RoutedLLM`.
- Mark tests that need the database `@pytest.mark.integration`. Stand-ins for `generate_sql`/`run_readonly` accept `**kw`.
- Run the real-model evaluation (`evals.run`) after any change to prompts, the model, the validator, the workflow graph or the dataset, and before accepting a new baseline. It exits 1 on any safety failure, data change or regression against `evals/baseline.json`. Reports go to `evals/reports/` (git-ignored).
- Prompt changes can make the model over-refuse. After editing `build_prompt`, run the real-model evaluation; the decline wording must state what always gets a query before saying when to decline.
- Golden numbers from the seed: completed revenue 1,380 total; 570 August, 810 September; September by region North 270, South 300, West 240; August North 250, South 200, West 120.

## Gotchas already hit

- The retail analyst login has column-level grants, so `SELECT *` on `customers`, `customer_addresses` or `employees` is refused by the database. Prompts and the catalog must list allowed columns only.
- Retail integration tests rebuild `retail_test` only; never point tests at `retail`.

- Inside Compose, use service names (`http://backend:8000`, `db:5432`); host port 5433 exists only outside Docker.
- A missing `environment:` entry (e.g. `BACKEND_URL` on the frontend) silently falls back to `localhost`.
- Each `.gitignore` entry needs its own line.
- `frontend/.dockerignore` does not exist yet, so `frontend/.venv` is sent with every frontend build (slower builds; the Dockerfile still copies only `app.py` and `client.py`).

## Status

M1–M22 committed (last checked: backend 129 passed, frontend 8 passed). M23a (audit trail: `app/audit.py`, `signed_in` dependency, `audit_event` calls; tests use the `audit_events` fixture instead of the database) is committed. M23b (login throttling: `app/throttle.py`, in-memory per username, 5 failures in 15 min lock for 15 min; tests get a fresh throttle via the `fresh_login_throttle` fixture) is committed, 140 backend tests passing. M23c (JSON logs via `app/logging_setup.py`, `LOG_FORMAT=json|text`; public `GET /ready` checks both databases) is committed, 144 backend tests passing. M23 is complete. M24a (dataset and harness) is committed. M24b (`evals/run.py`, real-model runner, and `evals/baseline.json`) is committed; 200 backend tests passing; baseline 20/20 scored cases, 3 of 3 each, with `non-data-hello` as the tracked known gap. M24 is complete. The `NO_QUERY` fix (prompt asks the model to answer exactly `NO_QUERY` for greetings, small talk and change requests; `is_no_query` in `text_to_sql.py`; `declined` node in the graph; `no_query` eval kind) is built, 214 backend tests passing, evaluation 23/23 scored cases 3 of 3 each, saved as the baseline; committed. The code is pushed to a private GitHub repository (`origin`). M25 (production images: lock files, multi-stage, uid 10001, read-only root, docs off by default, Trivy scan; image checks in `image_tests/`) is planned in `docs/build-plan.html` but paused. Phase 7 demo track comes first: M28 is complete (retail dataset: `db/retail/`, `backend/retail/`, `db/init/07_retail.sql`; backend 332 tests passing). Guardrails plan G1–G6 is drafted in `docs/build-plan.html` (not built; proposed order G1, G2, G3, G5 before M29, G4 after M29; awaiting the owner's decisions). Phase 7 parts: M28 retail dataset (generated, separate `retail` database), M29 data catalog (TOML files in `catalog/` plus database introspection), M30 retrieval over the catalog (OpenRouter embeddings, pgvector), M31 memory (persistent conversations, verified examples, user facts), M32 demo polish. Open suggestion not applied: converting midnight timestamps to dates for chart labels.
