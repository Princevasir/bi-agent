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
- Five specialist agents with one job each (`backend/app/agents/`): the **Coordinator** routes each message and rewrites follow-ups, **Knowledge** finds business knowledge and answers questions about the data, **SQL** writes, validates and runs one read-only query, **Analyst** writes a grounded answer, **Chart** picks or redraws the chart. `/ask` returns a `trace` of which agent did each step, and the audit trail records it.
- Ask about the data in plain English in a chat; the model writes the SQL (Qwen2.5 Coder 32B through OpenRouter, or any OpenRouter model via `OPENROUTER_MODEL`).
- Governed metric definitions (`revenue`, `order_count`) guide the model so "revenue" always means completed orders.
- Follow-up questions ("What about August?") are rewritten into a standalone question using the conversation; the UI shows how the question was interpreted.
- Relative dates such as "last month" are resolved from today's date.
- Generate SQL without running it (`POST /ask/sql`).
- Greetings, small talk and requests to change or delete data get a polite decline instead of a guessed query; nothing is run.

### Answers
- A short answer sentence, the SQL that produced it, and the result table.
- Every number in the model's sentence is checked against the result; if any number is not in the data, a plain answer built from the rows is shown instead.
- A fixed "no matching data" message for empty results, and a note when results were cut off.
- Automatic charts chosen by fixed rules from the shape of the result, never by the model, with a "Chart type" selector offering only the types that fit. Asking for a chart by name ("…as a pie chart") uses it when it fits and explains why when it doesn't; "make it a donut" redraws the last answer instantly without running a new query. Types: bar, pie, donut, treemap and funnel for categories; line, area and bar over time, one line per category when there are two dimensions; stacked and grouped bars, heatmap, treemap and Sankey for two categories; grouped bar and radar for several measures; scatter and bubble for numbers; histogram and box plot for distributions; a world map for countries; Gantt for start and end dates.
- Conversation history per user, readable through `GET /conversations/{id}`.

### Safety and access control
- Injection hardening (GR-INJ-01 to -03): questions, history, results and failed queries are fenced as data in every prompt; answers containing SQL, links or instruction-like text are replaced by the plain answer; the retail data contains planted injections (a product and a campaign name) that the adversarial evaluation reads.
- Every data answer shows its assumptions, read from the SQL: the date range and filters it used (GR-ACC-03). A "why" question answered from data never claims a cause; the answer says the data shows what happened, not why (GR-ACC-04).
- One deadline per question (GR-WF-02, 300 s): no further step starts after it.
- Privacy (GR-PRIV-01, -02, -04): personal columns (names, email, phone, street, postal code, salary) and any email address or phone number in the results are masked before the rows reach the model, while your screen still shows what your role may see; logs and the audit trail mask emails and phone numbers and record database errors by class only; requests to OpenRouter ask for no data collection by default.
- Per-user limits: 10 questions a minute and 200 a day (GR-COST-01), 600,000 tokens a day (GR-COST-02) and one running question at a time (GR-COST-03), each refused with a clear 429 and audited as `rate_limited`; with `STATE_STORE=postgres` they hold across backend instances.
- Cost check before execution (GR-SQL-03): every generated query is planned with `EXPLAIN` first, and one that would scan or join far too much (for example a product-level self-join of all order lines) is refused in milliseconds with "That question would scan too much data" instead of loading the database.
- Every generated query passes a validator before it runs: exactly one `SELECT` (or a `UNION`, `INTERSECT` or `EXCEPT` of them), no write hidden anywhere in it, allowed tables only, no schema-qualified names, only functions from an approved list (so nothing that runs SQL from a string, reads server settings, or builds huge values), no `SELECT INTO` or locking, no joins without a join condition, at most 8 tables and 3 levels of nested subqueries. Queries that are too broad get a message suggesting a more specific question.
- Queries run through a read-only database login with a 5-second timeout and a 200-row cap. Rows are read in small batches, so a query matching millions of rows never loads them into the backend.
- Two roles: `analyst` (orders and regions) and `limited` (regions only), each with its own database login, so the database refuses what the role may not read even if the validator were bypassed.
- The model only sees the tables the user's role may see, described from the data catalog (meaning, grain, allowed values, joins, known traps) when the retail data is connected.
- Personal data (names, email, phone, street address, postal code, salary) is refused before the database is reached, including through `SELECT *`, with a clear message.
- A query that fails because it is wrong gets "could not run, try rephrasing" rather than "database unavailable", after the model has had one chance to fix it with the error message. If the model wrongly declines a question that clearly mentions your data, it is asked once more; if it adds personal-data columns you did not ask for, it is asked to leave them out. Rule violations (forbidden tables, personal data, writes) are never retried.
- There is one way into the database for questions: the code refuses to run any SQL that did not come out of the validator, and a test fails if a new route skips sign-in.
- Conversations are private: another user's conversation ID returns "not found".

### Accounts and sign-in
- Local accounts with argon2id password hashing, created with a command-line tool that prompts for the password.
- JWT sign-in tokens (60 minutes by default); role and active status are re-read from the database on every request, so deactivating a user takes effect immediately.
- The same error for a wrong username or a wrong password.
- Lockout after 5 failed sign-ins within 15 minutes, for 15 minutes.
- Sign-in form, sign-out button and session-expired handling in the UI; the token never reaches the browser.

### Interface
- Ask about the data itself in the chat ("What tables do I have access to?", "Describe the orders table", "What does line_total mean?", "Which metrics are defined?"): answered instantly from the data catalog for your role, without the model.
- A Data catalog view in the sidebar: search and filter the tables your role can query, with columns, types, keys, relationships, caveats and governed metrics, and ask about any table in one click.
- A themed chat with a welcome screen of clickable example questions for your role, and the same examples in the sidebar.
- Each answer as a headline with tabs for an interactive Plotly chart, the table and the SQL; single numbers get a big-number card; monthly results are labelled "Aug 2026" rather than timestamps.
- Clear, distinct notes for declined questions, empty results, queries that were too broad or rejected, access denied, rate limits, timeouts and an unavailable model.
- Under each answer, a **Sources** line names the business documents the agents used (title, type, version), and a **How I answered** panel lists each agent's step in plain words with its time, plus the total.
- Streamlit's usage statistics are turned off.

### Reliability and operations
- Append-only audit trail of sign-ins, failed and locked sign-ins, questions (text, SQL, row count), rejected queries and access denials. Passwords, tokens, results and answers are never recorded.
- One-line JSON logs with request ID, user, path, status and time; `X-Request-ID` is accepted and returned on every response.
- `GET /health` (liveness) and `GET /ready` (both databases reachable).
- No runaway loops: every question stops within 15 workflow steps (`max_steps` in the policy file; the longest normal path takes 13), on top of the one-repair and one-second-opinion counters. A stopped run returns 422 with a plain message and is audited as `step_limit`.
- Shared state for more than one backend instance: with `STATE_STORE=postgres` (the Compose default) conversations, sign-in lockouts and token spending live in `appdb` (`db/init/09_shared_state.sql`), so a follow-up can be answered by any instance and survives a backend restart.
- An MCP server (`app/mcp_server.py`) with two tools, `ask_data` and `search_knowledge`, so Claude Desktop or Claude Code can use the BI Agent; it calls the API as a signed-in user, so every guardrail still applies.
- Retry and circuit breaker for each model provider: one retry with a short pause for transient failures, and after three failures in a row the provider is skipped for a minute, so the fallback answers at once or users get a clear "temporarily unavailable" message instead of waiting on a dead service (logged as `llm_retry`, `llm_circuit_open`, `llm_circuit_closed`).
- Optional fast mode with a fallback: `LLM_PROVIDER=groq` and `LLM_FALLBACK_PROVIDER=ollama` answer a retail question in about 2 seconds on Groq, and switch to the local model when Groq fails or is rate-limited (logged as `llm_fallback`).
- Timeouts, an output-token cap and a rolling hourly token budget for model calls, in total and per user, which refills on its own ("The question limit for this hour has been reached" when used up); model and database failures return clear, generic errors.
- The whole stack starts with one `docker compose up`.

### Demo data
- A generated retail dataset for a fictional outdoor-gear company, Trailhead Outfitters: 29 related tables in six business areas (sales, products, customers, supply chain, marketing and service, people), about 2.4 million rows from January 2024 to September 2026. Same seed, same data.
- Realistic structure: a category tree, a manager hierarchy, price history, many-to-many product suppliers, guest orders, returns per item, weekly stock levels.
- Planted business stories to discover, such as a late supplier delivery that empties tent stock and cuts March 2026 online revenue, a product recall, a promotion lift and a new store.
- Access enforced by the database down to the column: analysts cannot read customer names, email, phone, street address or salaries; managers can; limited users see only geography and products.

### Business knowledge (RAG, in progress)
- Index the knowledge pack (needs Ollama with `nomic-embed-text`: `ollama pull nomic-embed-text`): `cd backend && .venv/bin/python -m app.knowledge.ingest`. It is incremental: unchanged documents are skipped, changed ones re-embedded, deleted ones removed. Use `--rebuild` after changing the embedding model. The index lives in Postgres (`appdb`, schema `knowledge`).
- A knowledge pack for Trailhead Outfitters in `backend/knowledge/`: metric definitions with owners and versions (including one conflicting definition and how it is resolved), versioned business rules such as the February-to-January fiscal year, validated SQL examples that the tests execute, dashboard documentation, data-quality notes and incident reports. Retrieval and use by the agent are being added step by step (see `docs/rag.html`).
- Business questions answered from the documents (retail source): "How is revenue defined?", "When does the fiscal year start?", "Why did tent sales dip in March 2026?" or "What is our returns policy?" get a short answer from the knowledge documents, with each sentence citing its document, and no SQL. An answer that cites nothing, cites a document that was not retrieved, or adds a number not in the documents is replaced by the best document's own text. Questions about a table or column still go to the data catalog, and if no document matches, the question goes on to the catalog or SQL as before.
- Knowledge in answers (retail source): before writing SQL, the agent retrieves the business documents closest to the question (metric definitions, rules such as the February-to-January fiscal year, validated example queries) and gives them to the model as reference material, fenced and marked as not instructions. `/ask` returns them as `sources` and the audit trail records their IDs. If Ollama or the index is unavailable, the question is answered without knowledge and a warning is logged. The sample source never retrieves.
- Retrieval (`app/knowledge/retrieval.py`): finds the chunks closest to a question, only from active documents shared with the user's role and embedded by the same model, all filtered in SQL. Settings are in the `[knowledge]` section of `backend/policy/guardrails.toml` (`top_k`, `min_similarity`, `max_context_tokens`). Measure it with `cd backend && APP_DATABASE_URL=postgresql://app_rw:app_dev_pw@localhost:5433/appdb .venv/bin/python -m evals.retrieval` (38 labelled questions; reports Recall@K, Precision@K, MRR and latency).

### Testing and quality
- A demo dry run (`python -m evals.demo`) rehearses all 14 demo scenarios, happy and unhappy paths, on the real stack and fails loudly if any answer is wrong.
- Backend and frontend test suites; tests use a scripted model, so they are free and repeatable.
- An evaluation dataset of 23 questions with known answers, including follow-ups, an empty result, four safety probes and three requests that should be declined, with a scoring harness that checks the real workflow's results rather than its SQL text. A runner asks the real model every question, can repeat each one, compares with a saved baseline, and fails on any safety problem or regression.

## Prerequisites

- Docker Desktop (with Docker Compose v2)
- Python 3.12 or newer, only to run the test suites
- An [OpenRouter](https://openrouter.ai) API key with a small credit balance, to ask real questions

## Quick start

The demo in three commands (needs Docker Desktop and [Ollama](https://ollama.com) running; about a minute on a clean machine once the models are pulled):

```bash
cp .env.example .env
./scripts/setup.sh          # fills .env, checks Ollama, starts the stack, loads data, indexes knowledge, creates demo users
open http://localhost:8501  # sign in as demo-analyst or demo-limited
```

The script is safe to run again; it skips work already done and never prints secrets. The manual steps below do the same by hand.

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

On the first start, Postgres runs the scripts in `db/init/` to create the sample data, the read-only roles, the users database, and the empty retail demo databases. They only run on an empty data volume.

To fill the retail demo database (about 20 seconds, 350 MB):

```bash
cd backend
.venv/bin/python -m retail.load --scale full     # or --scale small for a quick 1% version
```

The complete catalog of the retail data (every table and column with its type, keys, relationships and meaning) is in [`docs/data-catalog.html`](docs/data-catalog.html) and `backend/catalog/generated/catalog.json`. After changing the catalog files or the schema, regenerate both with `cd backend && .venv/bin/python -m retail.export_catalog`.

Then set `DATA_SOURCE=retail` in `.env` and recreate the backend (`docker compose up -d backend`). Analysts can query all 29 tables except personal-data columns; limited users see geography and products only. With the local model, raise Ollama's context length to 16,384 (Ollama settings, or `launchctl setenv OLLAMA_CONTEXT_LENGTH 16384` and restart Ollama), because the retail prompt is about 4,700 tokens.

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
| POST | `/ask` | `{"message", "conversation_id"?}` → answer, SQL, assumptions (dates and filters the query used), rows, chart, sources (knowledge documents used), route, trace (agent, step and milliseconds for each step), conversation ID |
| POST | `/ask/sql` | Generate and validate SQL for a question without running it (422 if the validator rejects it) |
| GET | `/conversations/{id}` | Turns of one of your own conversations |
| GET | `/schema` | Tables and columns your role can see |
| GET | `/knowledge/search?q=` | The business documents closest to `q` that your role may read (used by the MCP tool) |
| GET | `/catalog` | The data catalog your role can see: tables, columns, keys, relationships, descriptions, metrics |
| GET | `/db/ping` | Database check as your role |
| POST | `/chat` | Plain LLM reply (no data access) |

Errors return a generic `{"detail": ...}`: 401 not signed in, 403 access denied, 404 conversation not found, 422 query rejected, 429 too many sign-in attempts or LLM rate limit, 502/503/504 for LLM or database problems. Details go to the server log, tagged with the request ID.

## Configuration

The guardrail rules (row, size, time and query-shape limits, the approved SQL functions, and which tables each role may query) live in one reviewed file, `backend/policy/guardrails.toml`. The backend refuses to start if it is malformed and logs its hash at start-up. The `SQL_*` variables below can only lower its limits, never raise them.


Set in `.env`; defaults come from `docker-compose.yml`.

| Variable | Default | Meaning |
|---|---|---|
| `JWT_SECRET` | none (required) | At least 32 characters; signs login tokens |
| `JWT_EXPIRE_MINUTES` | 60 | Token lifetime |
| `LLM_PROVIDER` | `fake` | `openrouter`, `groq` or `ollama` (a local model) for real answers |
| `GROQ_API_KEY`, `GROQ_MODEL` | none, `qwen/qwen3.8-27b` | For `LLM_PROVIDER=groq` (Groq's free tier allows about 8,000 tokens a minute; the evaluation runner waits out rate limits) |
| `OLLAMA_BASE_URL` | `http://localhost:11434/v1` (`host.docker.internal` inside Docker) | Ollama's OpenAI-compatible address |
| `OLLAMA_MODEL` | `qwen2.5-coder:7b` | Local model name |
| `OPENROUTER_API_KEY` | none | Your OpenRouter key |
| `OPENROUTER_MODEL` | `qwen/qwen-2.5-coder-32b-instruct` | Any OpenRouter model slug |
| `LLM_TIMEOUT_SECONDS` | 20 | Per LLM call |
| `LLM_MAX_OUTPUT_TOKENS` | 512 | Per LLM call |
| `LLM_PROVIDER_DATA_POLICY` | `deny` | What a hosted model provider may do with prompts (GR-PRIV-04): `deny` asks OpenRouter to route only to providers that do not collect data; `zdr` also requires zero data retention (with Groq it needs zero retention turned on in the Groq console and `GROQ_ZDR_CONFIRMED=true`, or the backend refuses to start); `allow` sends no preference. Ollama never leaves your machine |
| `LLM_FALLBACK_PROVIDER` | none | A second provider used when the first times out, is rate-limited or fails, e.g. `groq` first and `ollama` as fallback |
| `GROQ_TIMEOUT_SECONDS`, `OLLAMA_TIMEOUT_SECONDS`, `OPENROUTER_TIMEOUT_SECONDS` | `LLM_TIMEOUT_SECONDS` | Per-provider timeout, so a hosted model can fail fast while the local fallback gets longer |
| `LLM_RETRY_ATTEMPTS` | 2 | Attempts per model call for transient failures (throttling, 5xx, dropped connection); 1 switches retries off. Timeouts, configuration errors and our own budget are never retried |
| `LLM_BREAKER_FAILURES`, `LLM_BREAKER_COOLDOWN_SECONDS` | 3, 60 | After this many failures in a row a provider is skipped for the cooldown (503, or the fallback answers at once); one trial call then closes or reopens the breaker |
| `STATE_STORE` | `memory` (code), `postgres` (Compose) | Where conversations, the sign-in throttle and the token budget live: `postgres` shares them between backend instances and keeps conversations across restarts |
| `LLM_TOKEN_BUDGET` | 400000 | Tokens per rolling hour, all users together; when reached, questions get a 429 until older usage expires |
| `LLM_USER_TOKEN_BUDGET` | 150000 | Each user's share of the hourly budget (about 20 retail questions) |
| `LLM_TOKEN_BUDGET_WINDOW_SECONDS` | 3600 | Length of the rolling budget window |
| `LLM_USER_DAILY_TOKEN_BUDGET` | 600000 | Each user's tokens per rolling day, about 75 retail questions (GR-COST-02) |
| `RATE_PER_MINUTE`, `RATE_PER_DAY` | 10, 200 | Questions per user per minute and per day on `/ask`, `/ask/sql` and `/chat` (GR-COST-01); over the limit, 429 with `Retry-After` |
| `DATA_SOURCE` | `sample` | `retail` answers from the 29-table retail demo database (fill it first with `python -m retail.load --scale full`); `sample` uses the 12-row database the tests use |
| `GUARDRAIL_POLICY` | `backend/policy/guardrails.toml` | Path to the guardrail policy file |
| `SQL_MAX_ROWS` | 200 | Rows returned per query; more are never read from the database |
| `SQL_MAX_RESULT_BYTES` | 1000000 | Approximate size of the rows returned per query; a single larger row is refused |
| `SQL_TIMEOUT_MS` | 5000 | Statement timeout per query |
| `SQL_MAX_TABLES` | 8 | Table references allowed in one query |
| `SQL_MAX_DEPTH` | 3 | How deeply subqueries may be nested |
| `SQL_MAX_PLAN_COST`, `SQL_MAX_PLAN_ROWS` | 1000000, 10000000 | Planner estimates above which a generated query is refused before it runs (GR-SQL-03); rows are counted at the largest plan step |
| `REQUEST_DEADLINE_SECONDS` | 300 | Deadline for one question: no further workflow step starts after it, and the user gets 504 "That question took too long" (GR-WF-02) |
| `WORKFLOW_MAX_STEPS` | 15 | Steps one question may take through the workflow; a run that reaches it is stopped with a 422 |
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

### Using the BI Agent from Claude (MCP)

`backend/app/mcp_server.py` exposes the BI Agent as an MCP server with two tools: `ask_data` (a question in plain English; returns the answer, SQL, up to 20 rows, sources and a conversation ID for follow-ups) and `search_knowledge` (the closest business documents with excerpts). It signs in to the running backend as a normal user, so roles, guardrails, budgets and the audit trail all apply; the MCP client never reaches the database or the model directly.

Set it up once (`pip install -r requirements-mcp.txt` in `backend/.venv`; already included in `requirements-dev.txt`), then add it to Claude Code:

```bash
claude mcp add bi-agent \
  -e PYTHONPATH="$PWD/backend" -e BI_AGENT_URL=http://localhost:8000 \
  -e BI_AGENT_USERNAME=demo-analyst -e BI_AGENT_PASSWORD='<the demo password>' \
  -- "$PWD/backend/.venv/bin/python" -m app.mcp_server
```

or to Claude Desktop (`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{"mcpServers": {"bi-agent": {
  "command": "/full/path/to/backend/.venv/bin/python", "args": ["-m", "app.mcp_server"],
  "env": {"PYTHONPATH": "/full/path/to/backend", "BI_AGENT_URL": "http://localhost:8000",
          "BI_AGENT_USERNAME": "demo-analyst", "BI_AGENT_PASSWORD": "<the demo password>"}}}}
```

The password sits in your local client configuration, so use a dedicated BI Agent user. If the backend is down or a question is rejected, the tool returns the plain reason as a tool error.

### Demo dry run

Before presenting, rehearse every demo scenario automatically against the real stack (retail data, knowledge index, the model in `.env`):

```bash
cd backend && set -a && source ../.env && set +a && .venv/bin/python -m evals.demo     # about 2 minutes on the local model
```

It runs 14 scenarios from `backend/evals/demo_cases.json`: the happy paths (average order value, revenue by region and a pie-chart redraw, fiscal year and a follow-up, the catalog, two answers from the business documents) and deliberately broken ones (a delete request, a greeting, personal data, a limited user asking for revenue, the knowledge index down, the model down). Expected numbers come from fixed reference queries on the current data. It prints PASS or FAIL per scenario, checks the data is unchanged, and exits 1 on any failure. `--case ID` runs one scenario.

### Evaluating the real model

Without OpenRouter credit, use a free local model: install [Ollama](https://ollama.com), run `ollama pull qwen2.5-coder:7b`, set `LLM_PROVIDER=ollama` and `LLM_TIMEOUT_SECONDS=60` in `.env`, and prefix the commands below with `LLM_PROVIDER=ollama`. A full three-round evaluation takes about 4 minutes on an M1 Pro. Each model is compared with its own baseline in `backend/evals/baselines/`; if the provider fails, those cases are reported as "not scored" and the run exits with 2.

The unit tests use a scripted model. To check what the real model does with the 23 evaluation questions (this makes real API calls; one round uses roughly 9,000 tokens):

```bash
cd backend
set -a; source ../.env; set +a                 # loads LLM_PROVIDER and OPENROUTER_API_KEY
.venv/bin/python -m evals.run                  # every case once
.venv/bin/python -m evals.run --repeat 3       # three times each; a case passes on a majority
.venv/bin/python -m evals.run --case rev-month # one case
.venv/bin/python -m evals.run --update-baseline
```

The correct answer for each question is worked out at run time by running that case's reference query on the current data, so the evaluation stays valid if the data changes. Safety cases check which tables a query read, not specific values.

It needs the database running, prints a pass/fail table, and writes a full report (question, SQL, rows, answer) to `backend/evals/reports/`. It exits with 1 if any safety case fails, if the data changed during the run, or if a case that passed in the model's baseline (`backend/evals/baselines/<model>.json`) now fails; it exits with 2 if any case could not be scored.

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
  catalog/           data catalog: what every retail table and column means, governed metrics,
                     metric rules, SQL hints; generated/catalog.json is the full machine-readable catalog
  evals/             evaluation dataset (cases.json) and scoring harness
  retail/            retail demo data generator and loader
  tests/
frontend/
  app.py             Streamlit sign-in, chat and layout
  charts.py          Plotly figures from the backend's chart spec
  presentation.py    labels, number formats, big-number card, status messages
  client.py          HTTP calls to the backend
  .streamlit/        theme and privacy settings
  tests/
db/init/             SQL run on first start: schema, seed data, roles, users database
db/retail/           retail demo schema, foreign keys and indexes, read grants
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

Milestones 1 to 24 are done: the core question flow, follow-ups, charts, sign-in and roles, audit trail, sign-in throttling, JSON logs, a readiness check and a real-model evaluation suite. Next are production images, AWS deployment and CI/CD. See `docs/build-plan.html` for details.

Known limits today: conversations and the token budget are kept in memory and reset on restart; there is no TLS outside AWS; and result rows are sent to the model provider to write the explanation, so check its data policy before using real business data.
