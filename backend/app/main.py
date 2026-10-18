from fastapi import FastAPI

app = FastAPI(title="BI Agent API")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/hello")
def hello() -> dict[str, str]:
    return {"message": "Hello, BI Agent!"}