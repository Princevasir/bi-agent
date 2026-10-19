import logging
import os
import time
import uuid

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.llm import get_llm
from app.llm.base import (
    LLMConfigError, LLMError, LLMRateLimitError, LLMService, LLMTimeoutError,
)
from app.llm.budget import TokenBudget
from app.db import DBError, DBTimeoutError, run_readonly
from app.bi.schema import get_schema
from datetime import date

from app.bi.text_to_sql import generate_sql

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("bi_agent")

app = FastAPI(title="BI Agent API")
budget = TokenBudget(int(os.getenv("LLM_TOKEN_BUDGET", "50000")))

# Most specific first; LLMError is the catch-all.
LLM_ERRORS = [
    (LLMTimeoutError, 504, "The language model timed out."),
    (LLMRateLimitError, 429, "Too many requests to the language model."),
    (LLMConfigError, 503, "The language model is not configured correctly."),
    (LLMError, 502, "The language model request failed."),
]

def make_generate(llm, request):
    def generate(prompt: str) -> str:
        budget.check()
        result = llm.generate(prompt)
        budget.record(result.input_tokens + result.output_tokens)
        logger.info("request_id=%s llm_tokens in=%s out=%s",
                    request.state.request_id, result.input_tokens, result.output_tokens)
        return result.text
    return generate


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = request_id
    start = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    ms = (time.perf_counter() - start) * 1000
    logger.info("request_id=%s %s %s -> %s %.1fms", request_id,
                request.method, request.url.path, response.status_code, ms)
    return response


@app.exception_handler(LLMError)
async def llm_error_handler(request: Request, exc: LLMError):
    for cls, status, message in LLM_ERRORS:
        if isinstance(exc, cls):
            logger.warning("request_id=%s llm_error=%s detail=%s",
                           getattr(request.state, "request_id", "-"), type(exc).__name__, exc)
            return JSONResponse(status_code=status, content={"detail": message})


class ChatRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    message: str = Field(min_length=1, max_length=2000)


class ChatResponse(BaseModel):
    reply: str


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/hello")
def hello() -> dict[str, str]:
    return {"message": "Hello, BI Agent!"}


@app.post("/chat", response_model=ChatResponse)
def chat(body: ChatRequest, request: Request,
         llm: LLMService = Depends(get_llm)) -> ChatResponse:
    budget.check()
    result = llm.generate(body.message)
    budget.record(result.input_tokens + result.output_tokens)
    logger.info("request_id=%s llm_tokens in=%s out=%s", request.state.request_id,
                result.input_tokens, result.output_tokens)
    return ChatResponse(reply=result.text)


@app.get("/db/ping")
def db_ping():
    return run_readonly("SELECT 1 AS result")


@app.exception_handler(DBError)
async def db_error_handler(request: Request, exc: DBError):
    if isinstance(exc, DBTimeoutError):
        status, message = 504, "The database query timed out."
    else:
        status, message = 503, "The database is unavailable."
    logger.warning("request_id=%s db_error=%s detail=%s",
                   getattr(request.state, "request_id", "-"), type(exc).__name__, exc)
    return JSONResponse(status_code=status, content={"detail": message})

@app.get("/schema")
def schema():
    return get_schema()

@app.post("/ask/sql")
def ask_sql(body: ChatRequest, request: Request, llm: LLMService = Depends(get_llm)):
    sql = generate_sql(body.message, make_generate(llm, request), date.today())
    return {"question": body.message, "sql": sql}