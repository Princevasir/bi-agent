# BI Agent MVP — guidance for Claude

A natural-language BI agent: users ask questions in plain English and get a grounded answer, the SQL, a table and a chart. Built in small, verified milestones (M1–M27). `README.md` covers setup and usage; this file covers how to work on the code.

## Keep the docs current

- `docs/build-plan.html` is the living plan: roadmap, step-by-step milestone guides, development log, known limits. Update it whenever the plan changes, a milestone starts or finishes, a decision is made, or a new limit appears. Keep the "Last updated" line and the development log current, and label results as **seen** (output observed) or **reported** (the owner said so).
- Edit it in place; git keeps history. Never create new `_vN` copies. The older `docs/BI Agent MVP_ incremental build plan*.html` files are historical only.
- Update `README.md` when setup steps, configuration, API routes, roles or user-visible behavior change.
- Update this file when conventions, layout or status change.

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
```

Code changes need `--build`; `.env` or compose environment changes need the container recreated.

## Architecture

- Logs are one JSON object per line: log with a short message and `extra={...}` fields (`request_id`, `username`, ...), not formatted strings, for anything worth searching.
- `backend/app/main.py`: routes, exception handlers (each maps to a generic client message; details go to logs with the request ID), request-ID middleware, `make_generate` (token budget + logging around every LLM call), `conv_key`.
- `auth.py` (argon2, JWT HS256, `current_user`), `appdb.py` (users table in `appdb`), `cli.py` (create-user), `access.py` (`ROLE_TABLES`, `ROLE_DB_ENV`, `AccessError`).
- `db.py`: `run_readonly(sql, params, max_rows, timeout_ms, role)` — the role picks the database login; read-only transaction, statement timeout, row cap.
- `llm/`: `LLMService` interface, `openrouter.py`, `fake.py`, `budget.py`, typed errors (timeout, rate limit, config, generic).
- `bi/`: `metrics.py` (governed metrics + deterministic builder), `schema.py` (per-role schema text), `text_to_sql.py` (prompt + extraction), `sql_guard.py` (sqlglot validator), `service.py` (LangGraph graph: rewrite → write_sql → check_sql → execute → explain → ground, or no_rows), `grounding.py`, `rewrite.py`, `chart.py`, `conversation.py`.
- `frontend/app.py`: Streamlit sign-in gate, chat, table, chart. `client.py`: `post_json`/`get_json`/`login`, raises `BackendError` with the backend's message and status.
- `db/init/`: `01_schema`, `02_seed`, `03_roles` (bi_readonly), `04_limited_role` (bi_limited), `05_app_db` (appdb, app_rw, users), `06_audit` (audit.events, insert-only for app_rw). Run only on an empty volume.

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
- Golden numbers from the seed: completed revenue 1,380 total; 570 August, 810 September; September by region North 270, South 300, West 240; August North 250, South 200, West 120.

## Gotchas already hit

- Inside Compose, use service names (`http://backend:8000`, `db:5432`); host port 5433 exists only outside Docker.
- A missing `environment:` entry (e.g. `BACKEND_URL` on the frontend) silently falls back to `localhost`.
- Each `.gitignore` entry needs its own line.
- `frontend/.dockerignore` does not exist yet, so `frontend/.venv` is sent with every frontend build (slower builds; the Dockerfile still copies only `app.py` and `client.py`).

## Status

M1–M22 committed (last checked: backend 129 passed, frontend 8 passed). M23a (audit trail: `app/audit.py`, `signed_in` dependency, `audit_event` calls; tests use the `audit_events` fixture instead of the database) is committed. M23b (login throttling: `app/throttle.py`, in-memory per username, 5 failures in 15 min lock for 15 min; tests get a fresh throttle via the `fresh_login_throttle` fixture) is committed, 140 backend tests passing. M23c (JSON logs via `app/logging_setup.py`, `LOG_FORMAT=json|text`; public `GET /ready` checks both databases) is committed, 144 backend tests passing. M23 is complete. Next: M24, regression and evaluation dataset. Open suggestions not applied: a `NO_QUERY` path for non-data questions, and converting midnight timestamps to dates for chart labels.
