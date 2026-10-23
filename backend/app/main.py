import logging
import os
import time
import uuid
from dataclasses import asdict
from datetime import date
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app import audit
from app.access import AccessError, tables_for
from app.appdb import User, get_user
from app.appdb import ping as appdb_ping
from app.auth import AuthConfigError, authenticate, create_token, current_user
from app.bi.conversation import MAX_STORED_ROWS, ConversationStore, Turn
from app.bi.schema import get_schema
from app.bi.service import answer_question
from app.bi.sql_guard import SQLRejected, validate_sql
from app.bi.text_to_sql import generate_sql, is_no_query
from app.db import DBError, DBTimeoutError, TrustedSQL, run_readonly
from app.llm import get_llm
from app.llm.base import (
    LLMConfigError, LLMError, LLMRateLimitError, LLMService, LLMTimeoutError,
)
from app.llm.budget import TokenBudget
from app.logging_setup import configure_logging
from app.throttle import LoginThrottle

configure_logging()
logger = logging.getLogger("bi_agent")

app = FastAPI(title="BI Agent API")
budget = TokenBudget(int(os.getenv("LLM_TOKEN_BUDGET", "50000")))
store = ConversationStore()
throttle = LoginThrottle()

# Most specific first; LLMError is the catch-all.
LLM_ERRORS = [
    (LLMTimeoutError, 504, "The language model timed out."),
    (LLMRateLimitError, 429, "Too many requests to the language model."),
    (LLMConfigError, 503, "The language model is not configured correctly."),
    (LLMError, 502, "The language model request failed."),
]


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = request_id
    start = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    ms = (time.perf_counter() - start) * 1000
    user = getattr(request.state, "user", None)
    logger.info("request", extra={
        "request_id": request_id, "method": request.method, "path": request.url.path,
        "status": response.status_code, "ms": round(ms, 1),
        "username": user.username if user else None,
    })
    return response


def _rid(request: Request):
    return getattr(request.state, "request_id", "-")


def signed_in(request: Request, user: User = Depends(current_user)):
    request.state.user = user
    return user


def audit_event(request, event, status_code, username=None, **detail):
    user = getattr(request.state, "user", None)
    audit.record(
        event,
        request_id=_rid(request),
        username=username or (user.username if user else None),
        role=user.role if user else None,
        status_code=status_code,
        **detail,
    )


@app.exception_handler(LLMError)
async def llm_error_handler(request: Request, exc: LLMError):
    for cls, status, message in LLM_ERRORS:
        if isinstance(exc, cls):
            logger.warning("request_id=%s llm_error=%s detail=%s",
                           _rid(request), type(exc).__name__, exc)
            audit_event(request, "llm_error", status, error=type(exc).__name__)
            return JSONResponse(status_code=status, content={"detail": message})


@app.exception_handler(DBError)
async def db_error_handler(request: Request, exc: DBError):
    if isinstance(exc, DBTimeoutError):
        status, message = 504, "The database query timed out."
    else:
        status, message = 503, "The database is unavailable."
    logger.warning("request_id=%s db_error=%s detail=%s cause=%r",
                   _rid(request), type(exc).__name__, exc, exc.__cause__)
    audit_event(request, "db_error", status, error=type(exc).__name__)
    return JSONResponse(status_code=status, content={"detail": message})


@app.exception_handler(SQLRejected)
async def sql_rejected_handler(request: Request, exc: SQLRejected):
    logger.warning("request_id=%s sql_rejected=%s", _rid(request), exc)
    audit_event(request, "sql_rejected", 422, reason=str(exc))
    return JSONResponse(status_code=422, content={"detail": "The generated query was rejected."})


@app.exception_handler(AuthConfigError)
async def auth_config_handler(request: Request, exc: AuthConfigError):
    logger.error("request_id=%s auth_config_error=%s", _rid(request), exc)
    return JSONResponse(status_code=503, content={"detail": "Authentication is not configured."})


@app.exception_handler(AccessError)
async def access_error_handler(request: Request, exc: AccessError):
    logger.warning("request_id=%s access_denied=%s", _rid(request), exc)
    audit_event(request, "access_denied", 403, reason=str(exc))
    return JSONResponse(status_code=403, content={"detail": "Access denied."})


class ChatRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    message: str = Field(min_length=1, max_length=2000)


class ChatResponse(BaseModel):
    reply: str


class AskRequest(ChatRequest):
    conversation_id: UUID | None = None


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


def make_generate(llm, request):
    def generate(prompt: str) -> str:
        budget.check()
        result = llm.generate(prompt)
        budget.record(result.input_tokens + result.output_tokens)
        logger.info("llm_tokens", extra={
            "request_id": request.state.request_id,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
        })
        return result.text
    return generate


def conv_key(user, conversation_id):
    return f"{user.username}:{conversation_id}"


# ---- public routes ----

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/hello")
def hello() -> dict[str, str]:
    return {"message": "Hello, BI Agent!"}


@app.get("/ready")
def ready():
    checks = {}
    for name, check in (("analytics", lambda: run_readonly(TrustedSQL("SELECT 1"))),
                        ("appdb", appdb_ping)):
        try:
            check()
            checks[name] = "ok"
        except DBError:
            checks[name] = "unavailable"
    ok = all(v == "ok" for v in checks.values())
    return JSONResponse(status_code=200 if ok else 503,
                        content={"status": "ready" if ok else "not ready", "checks": checks})


@app.post("/auth/login")
def login(body: LoginRequest, request: Request):
    name = body.username.strip().lower()
    if throttle.is_locked(name):
        audit_event(request, "login_locked", 429, username=name)
        raise HTTPException(status_code=429, detail="Too many sign-in attempts. Try again later.")
    user = get_user(name)
    if not authenticate(user, body.password):
        throttle.record_failure(name)
        audit_event(request, "login_failure", 401, username=name)
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    throttle.record_success(name)
    request.state.user = user
    audit_event(request, "login_success", 200)
    return {"access_token": create_token(user.username, user.role),
            "token_type": "bearer", "role": user.role}


# ---- protected routes ----

@app.post("/chat", response_model=ChatResponse, dependencies=[Depends(signed_in)])
def chat(body: ChatRequest, request: Request,
         llm: LLMService = Depends(get_llm)) -> ChatResponse:
    result_text = make_generate(llm, request)(body.message)
    return ChatResponse(reply=result_text)


@app.get("/db/ping")
def db_ping(user: User = Depends(signed_in)):
    return run_readonly(TrustedSQL("SELECT 1 AS result"), role=user.role)


@app.get("/schema")
def schema(user: User = Depends(signed_in)):
    return get_schema(user.role)


@app.post("/ask/sql")
def ask_sql(body: ChatRequest, request: Request,
            user: User = Depends(signed_in),
            llm: LLMService = Depends(get_llm)):
    sql = generate_sql(body.message, make_generate(llm, request), date.today(), role=user.role)
    sql = "" if is_no_query(sql) else validate_sql(sql, tables_for(user.role))
    audit_event(request, "ask_sql", 200, question=body.message, sql=sql)
    return {"question": body.message, "sql": sql}


@app.post("/ask")
def ask(body: AskRequest, request: Request,
        user: User = Depends(signed_in),
        llm: LLMService = Depends(get_llm)):
    if body.conversation_id is None:
        cid, history = store.new_id(), []
    else:
        cid = str(body.conversation_id)
        history = store.get(conv_key(user, cid))
        if history is None:
            raise HTTPException(status_code=404, detail="Conversation not found.")
    out = answer_question(body.message, make_generate(llm, request),
                          date.today(), history, role=user.role)
    store.add(conv_key(user, cid), Turn(
        question=body.message,
        sql=out["sql"],
        columns=out["columns"],
        rows=out["rows"][:MAX_STORED_ROWS],
        answer=out["answer"],
    ))
    audit_event(request, "ask", 200,
                conversation_id=cid, question=body.message,
                interpreted_as=out["interpreted_as"], sql=out["sql"],
                row_count=len(out["rows"]), truncated=out["truncated"],
                answer_source=out["answer_source"])
    return {**out, "conversation_id": cid}


@app.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: UUID, user: User = Depends(signed_in)):
    cid = str(conversation_id)
    turns = store.get(conv_key(user, cid))
    if turns is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return {"conversation_id": cid, "turns": [asdict(t) for t in turns]}