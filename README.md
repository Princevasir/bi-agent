# BI Agent

Ask questions about business data in plain English and get back a short answer, the SQL that produced it, a results table, and a chart.

> "What was revenue by region in September 2026?"
> → North 270, South 300, West 240, with the query, a table and a bar chart.
> "What about August?"
> → understood as "revenue by region in August 2026" and answered the same way.

This is an MVP built in small, tested milestones. The full plan, step-by-step guides and development log live in [`docs/build-plan.html`](docs/build-plan.html) (open it in a browser).

## How it works

```
Browser ──► Streamlit UI (:8501) ──► FastAPI backend (:8000) ──► PostgreSQL (analytics, appdb)
                                            │
                                            └──► LLM via OpenRouter (Qwen2.5 Coder 32B)
```

For each question the backend runs a small LangGraph workflow:

1. **Rewrite** a follow-up into a standalone question, using the last few turns (only when there is history).
2. **Write SQL** with the LLM, from the schema and metric definitions the user's role may see.
3. **Check SQL** with a deterministic validator (sqlglot): exactly one `SELECT`, allowed tables only.
4. **Execute** read-only, with a timeout and a row cap, using a database login that matches the user's role.
5. **Explain** the result in a sentence, then **ground** it: every number must appear in the result, otherwise a plain answer built from the rows is used.

The chart type is chosen by fixed backend rules, never by the model.

## Features

The full list of what the project offers today. Keep it current as features land.

### Asking questions
- Ask about the data in plain English in a chat; the model writes the SQL (Qwen2.5 Coder 32B through OpenRouter, or any OpenRouter model via `OPENROUTER_MODEL`).
- Governed metric definitions (`revenue`, `order_count`) guide the model so "revenue" always means completed orders.
- Follow-up questions ("What about August?") are rewritten into a standalone question using the conversation; the UI shows how the question was interpreted.
- Relative dates such as "last month" are resolved from today's date.
- Generate SQL without running it (`POST /ask/sql`).

### Answers
- A short answer sentence, the SQL that produced it, and the result table.
- Every number in the model's sentence is checked against the result; if any number is not in the data, a plain answer built from the rows is shown instead.
- A fixed "no matching data" message for empty results, and a note when results were cut off.
- Automatic charts: a line chart for dates or months, a bar chart for categories, none when it wouldn't help. Chosen by fixed rules, never by the model.
- Conversation history per user, readable through `GET /conversations/{id}`.

### Safety and access control
- Every generated query passes a validator before it runs: exactly one `SELECT`, allowed tables only, no schema-qualified names, no dangerous functions, no `SELECT INTO` or locking.
- Queries run through a read-only database login with a 5-second timeout and a 200-row cap.
- Two roles: `analyst` (orders and regions) and `limited` (regions only), each with its own database login, so the database refuses what the role may not read even if the validator were bypassed.
- The model only sees the tables the user's role may see.
- Conversations are private: another user's conversation ID returns "not found".

### Accounts and sign-in
- Local accounts with argon2id password hashing, created with a command-line tool that prompts for the password.
- JWT sign-in tokens (60 minutes by default); role and active status are re-read from the database on every request, so deactivating a user takes effect immediately.
- The same error for a wrong username or a wrong password.
- Lockout after 5 failed sign-ins within 15 minutes, for 15 minutes.
- Sign-in form, sign-out button and session-expired handling in the UI; the token never reaches the browser.

### Reliability and operations
- Append-only audit trail of sign-ins, failed and locked sign-ins, questions (text, SQL, row count), rejected queries and access denials. Passwords, tokens, results and answers are never recorded.
- One-line JSON logs with request ID, user, path, status and time; `X-Request-ID` is accepted and returned on every response.
- `GET /health` (liveness) and `GET /ready` (both databases reachable).
- Timeouts, an output-token cap and a total token budget for model calls; model and database failures return clear, generic errors.
- The whole stack starts with one `docker compose up`.

### Testing and quality
- Backend and frontend test suites; tests use a scripted model, so they are free and repeatable.
- An evaluation dataset of 21 questions with known answers, including follow-ups, an empty result, four safety probes and one tracked known gap, with a scoring harness that checks the real workflow's results rather than its SQL text. (A runner for the real model and a saved baseline are coming next.)

## Prerequisites

- Docker Desktop (with Docker Compose v2)
- Python 3.12 or newer, only to run the test suites
- An [OpenRouter](https://openrouter.ai) API key with a small credit balance, to ask real questions

## Quick start

From the repository root:

```bash
cp .env.example .env
openssl rand -hex 32          # paste the output as JWT_SECRET in .env
```

Edit `.env`:

```
JWT_SECRET=<the value you generated>
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=<your key>
```

`.env` is git-ignored; never commit it. With `LLM_PROVIDER=fake` (the default) the app starts and the tests run, but the fake model only echoes text, so questions will be rejected.

Start everything and create a user:

```bash
docker compose up --build -d
docker compose ps                                          # backend and db should be "healthy"
docker compose exec backend python -m app.cli create-user alice analyst
```

The CLI prompts for a password (at least 12 characters). Then open http://localhost:8501, sign in, and ask a question. The API docs are at http://localhost:8000/docs.

On the first start, Postgres runs the scripts in `db/init/` to create the sample data, the read-only roles, and the users database. They only run on an empty data volume.

## Roles

| Role | Can query | Database login |
|---|---|---|
| `analyst` | `orders`, `regions` | `bi_readonly` |
| `limited` | `regions` only | `bi_limited` |

The role is read from the users table on every request. A limited user's question about revenue is rejected by the SQL validator, and the database login would refuse it anyway. The table `internal_notes` is readable by neither role.

## Sample data

| Table | Contents |
|---|---|
| `regions` | North, South, West |
| `orders` | 12 orders in August and September 2026 (10 completed, 2 cancelled) |
| `internal_notes` | One row that no BI login can read; used to test access control |

Governed metrics: `revenue` (sum of completed order amounts) and `order_count` (number of completed orders), by `region` or `month`. Known answers: completed revenue is 1,380 in total, 570 in August and 810 in September.

## API

All routes except the first four need `Authorization: Bearer <token>` from `/auth/login`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness check (used by Docker) |
| GET | `/hello` | Smoke test |
| GET | `/ready` | Readiness: 200 when both databases answer, 503 otherwise |
| POST | `/auth/login` | `{"username", "password"}` → access token and role |
| POST | `/ask` | `{"message", "conversation_id"?}` → answer, SQL, rows, chart, conversation ID |
| POST | `/ask/sql` | Generate SQL for a question without running it |
| GET | `/conversations/{id}` | Turns of one of your own conversations |
| GET | `/schema` | Tables and columns your role can see |
| GET | `/db/ping` | Database check as your role |
| POST | `/chat` | Plain LLM reply (no data access) |

Errors return a generic `{"detail": ...}`: 401 not signed in, 403 access denied, 404 conversation not found, 422 query rejected, 429 too many sign-in attempts or LLM rate limit, 502/503/504 for LLM or database problems. Details go to the server log, tagged with the request ID.

## Configuration

Set in `.env`; defaults come from `docker-compose.yml`.

| Variable | Default | Meaning |
|---|---|---|
| `JWT_SECRET` | none (required) | At least 32 characters; signs login tokens |
| `JWT_EXPIRE_MINUTES` | 60 | Token lifetime |
| `LLM_PROVIDER` | `fake` | `openrouter` for real answers |
| `OPENROUTER_API_KEY` | none | Your OpenRouter key |
| `OPENROUTER_MODEL` | `qwen/qwen-2.5-coder-32b-instruct` | Any OpenRouter model slug |
| `LLM_TIMEOUT_SECONDS` | 20 | Per LLM call |
| `LLM_MAX_OUTPUT_TOKENS` | 512 | Per LLM call |
| `LLM_TOKEN_BUDGET` | 50000 | Total tokens per backend process before LLM calls are refused |
| `LOG_LEVEL` | `INFO` | Backend log level |
| `LOG_FORMAT` | `json` | `json` (one JSON object per line) or `text` for easier local reading |

The database URLs in `docker-compose.yml` use local development passwords. Replace them with real secrets for any shared or deployed environment.

## Running the tests

Each service has its own virtual environment.

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest                       # needs: docker compose up -d db
.venv/bin/python -m pytest -m "not integration"  # without the database

cd ../frontend
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

Tests never call the real LLM: they use a scripted fake model (`backend/tests/routed_llm.py`). Integration tests connect to the Compose database on host port 5433.

The evaluation dataset lives in `backend/evals/cases.json` and the scoring code in `backend/evals/harness.py`; `tests/test_evals.py` checks that every expected answer is right and that the scoring rules behave.

## Project layout

```
backend/
  app/
    main.py          API routes, error handlers, request-ID middleware
    auth.py          password hashing, JWT, current_user
    appdb.py         users table access
    cli.py           create-user command
    access.py        role → allowed tables and database login
    db.py            run_readonly(): read-only, timeout, row cap
    llm/             LLM interface, OpenRouter and fake providers, token budget
    bi/              metrics, schema, text-to-SQL, SQL validator, workflow graph,
                     grounding, follow-up rewrite, chart rules, conversation store
  evals/             evaluation dataset (cases.json) and scoring harness
  tests/
frontend/
  app.py             Streamlit sign-in and chat
  client.py          HTTP calls to the backend
  tests/
db/init/             SQL run on first start: schema, seed data, roles, users database
docs/build-plan.html Roadmap, step-by-step guides, development log, known limits
docker-compose.yml
```

## Troubleshooting

- **Port 5432 already in use:** the database is published on host port 5433 for that reason. Containers still use `db:5432`.
- **A setting in `.env` has no effect:** recreate the container: `docker compose up --build -d`.
- **Changes to `db/init/` have no effect:** those scripts run only on an empty volume. Apply a script to the running database with `docker compose exec -T db psql -U admin -d postgres < db/init/<file>.sql`, or reset everything with `docker compose down -v` (this deletes all users and data).
- **"Authentication is not configured":** `JWT_SECRET` is missing or shorter than 32 characters.
- **"The generated query was rejected":** the model's SQL broke a rule (wrong table, not a single SELECT), or your role may not see that data.
- **"Too many sign-in attempts":** five wrong passwords within 15 minutes lock that username for 15 minutes. During development, `docker compose restart backend` clears it.
- **"Not authenticated" in the UI:** your session ended; sign in again. A page refresh also signs you out.

## Status and limits

Milestones 1 to 23 are done: the core question flow, follow-ups, charts, sign-in and roles, audit trail, sign-in throttling, JSON logs and a readiness check. Next are an evaluation dataset, production images, AWS deployment and CI/CD. See `docs/build-plan.html` for details.

Known limits today: conversations and the token budget are kept in memory and reset on restart; there is no TLS outside AWS; greetings such as "hello" still trigger a guessed query; and result rows are sent to the model provider to write the explanation, so check its data policy before using real business data.
