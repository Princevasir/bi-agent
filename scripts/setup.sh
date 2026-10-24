#!/usr/bin/env bash
# One-command demo setup (demo gap D4). Safe to run again: every step skips work that is already done.
#
#   cp .env.example .env      # optional; this script creates .env if it is missing
#   ./scripts/setup.sh
#   open http://localhost:8501
#
# Needs Docker Desktop and Ollama (https://ollama.com) running. Never prints secrets.
# DEMO_PASSWORD=... sets the demo users' password without a prompt (at least 12 characters).
set -euo pipefail
cd "$(dirname "$0")/.."

OLLAMA=http://localhost:11434
MIN_CONTEXT=16384
USERS=("demo-analyst analyst" "demo-limited limited")

say()  { printf '\n==> %s\n' "$*"; }
note() { printf '    %s\n' "$*"; }
fail() { printf '\nSetup stopped: %s\n' "$*" >&2; exit 1; }
env_get() { grep -E "^$1=" .env | tail -1 | cut -d= -f2- || true; }

wait_ready() {
  for _ in $(seq 1 90); do
    curl -sf http://localhost:8000/ready >/dev/null 2>&1 && return 0
    sleep 2
  done
  docker compose ps
  fail "the backend did not become ready in 3 minutes. See: docker compose logs backend"
}

say "Checking prerequisites"
command -v docker >/dev/null || fail "Docker is not installed. Install Docker Desktop and run this again."
docker info >/dev/null 2>&1 || fail "Docker is not running. Start Docker Desktop and run this again."
command -v python3 >/dev/null || fail "python3 is missing (macOS: xcode-select --install)."
command -v curl >/dev/null || fail "curl is missing."
note "Docker and python3 found."

say "Preparing .env (values are never printed)"
python3 scripts/prepare_env.py .env .env.example | sed 's/^/    /'
PROVIDER=$(env_get LLM_PROVIDER)
MODEL=$(env_get OLLAMA_MODEL); MODEL=${MODEL:-qwen2.5-coder:7b}

say "Checking Ollama"
curl -sf "$OLLAMA/api/tags" >/dev/null || fail "Ollama is not running at $OLLAMA. Install it from https://ollama.com, open it, and run this again."
NEEDED=("nomic-embed-text")                       # the knowledge index always uses local embeddings
[ "$PROVIDER" = "ollama" ] && NEEDED+=("$MODEL")
for m in "${NEEDED[@]}"; do
  if curl -s "$OLLAMA/api/tags" | grep -q "\"name\":\"$m"; then
    note "$m is available."
  else
    command -v ollama >/dev/null || fail "model $m is missing and the ollama command is not on PATH. Run: ollama pull $m"
    note "Pulling $m (first time only; a few GB for the chat model)..."
    ollama pull "$m"
  fi
done
if [ "$PROVIDER" = "ollama" ]; then
  curl -s "$OLLAMA/api/generate" -d "{\"model\":\"$MODEL\",\"prompt\":\"ok\",\"stream\":false,\"options\":{\"num_predict\":1}}" >/dev/null
  CONTEXT=$(curl -s "$OLLAMA/api/ps" | python3 -c "
import json, sys
models = json.load(sys.stdin).get('models', [])
print(next((m.get('context_length', 0) for m in models if m.get('name') == sys.argv[1]), 0))" "$MODEL")
  if [ "${CONTEXT:-0}" -ge "$MIN_CONTEXT" ]; then
    note "$MODEL runs with a context of $CONTEXT tokens."
  else
    note "WARNING: $MODEL runs with a context of ${CONTEXT:-unknown} tokens; the retail prompts need $MIN_CONTEXT."
    note "Fix: Ollama > Settings > Context length 16k (or: launchctl setenv OLLAMA_CONTEXT_LENGTH $MIN_CONTEXT),"
    note "then quit and reopen Ollama. Answers will be unreliable until then."
  fi
fi

say "Starting the stack (database, backend, frontend)"
docker compose up --build -d
wait_ready
note "Backend is ready."

say "Applying database updates (safe to repeat)"
for f in db/init/09_shared_state.sql db/init/10_request_limits.sql; do
  docker compose exec -T db psql -q -U admin -d postgres -v ON_ERROR_STOP=1 < "$f" >/dev/null
done
note "Shared state tables are in place."

say "Loading the retail demo data"
ORDERS=$(docker compose exec -T db psql -U admin -d retail -Atc "SELECT count(*) FROM orders" 2>/dev/null || echo 0)
if [ "${ORDERS:-0}" -gt 0 ] 2>/dev/null; then
  note "Already loaded ($ORDERS orders); skipped."
else
  docker compose --profile setup run --rm setup python -m retail.load --scale full | tail -1 | sed 's/^/    /'
  docker compose restart backend >/dev/null
  wait_ready
fi

say "Indexing the business knowledge (only new or changed documents are embedded)"
docker compose --profile setup run --rm setup python -m app.knowledge.ingest | sed 's/^/    /'

say "Creating demo users"
MISSING=$(docker compose exec -T db psql -U admin -d appdb -Atc \
  "SELECT count(*) FROM (VALUES ('demo-analyst'), ('demo-limited')) v(u) WHERE u NOT IN (SELECT username FROM users)")
if [ "${MISSING:-2}" -eq 0 ]; then
  note "demo-analyst and demo-limited already exist; skipped."
else
  PASSWORD=${DEMO_PASSWORD:-}
  if [ -z "$PASSWORD" ] && [ -t 0 ]; then
    read -r -s -p "    Choose a password for the demo users (at least 12 characters): " PASSWORD; echo
    read -r -s -p "    Repeat it: " AGAIN; echo
    [ "$PASSWORD" = "$AGAIN" ] || fail "the passwords did not match. Run this again."
  fi
  if [ -z "$PASSWORD" ]; then
    note "No terminal to ask for a password, so no users were created."
    note "Run ./scripts/setup.sh again in a terminal, or set DEMO_PASSWORD."
  else
    [ ${#PASSWORD} -ge 12 ] || fail "the password must be at least 12 characters."
    for entry in "${USERS[@]}"; do
      read -r name role <<<"$entry"
      printf '%s\n' "$PASSWORD" | docker compose exec -T backend \
        python -m app.cli create-user "$name" "$role" --password-stdin --exist-ok | sed 's/^/    /'
    done
  fi
fi

say "Done"
note "Open http://localhost:8501 and sign in as demo-analyst (all retail data except personal details)"
note "or demo-limited (geography and products only). Try: What was the average order value in 2025?"
[ "$PROVIDER" = "ollama" ] && note "On the local model each answer takes 20 to 40 seconds."
exit 0
