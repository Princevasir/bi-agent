import logging
import os
import time
import uuid

from fastapi import FastAPI, Request

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("bi_agent")

app = FastAPI(title="BI Agent API")


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    start = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    ms = (time.perf_counter() - start) * 1000
    logger.info("request_id=%s %s %s -> %s %.1fms", request_id,
                request.method, request.url.path, response.status_code, ms)
    return response

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/hello")
def hello() -> dict[str, str]:
    return {"message": "Hello, BI Agent!"}