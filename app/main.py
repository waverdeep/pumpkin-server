from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.routers import baskets

app = FastAPI(title="사탕바구니 API", version="0.1.0", docs_url="/api/docs", openapi_url="/api/openapi.json")
app.include_router(baskets.router)


@app.exception_handler(RequestValidationError)
async def validation_handler(_: Request, exc: RequestValidationError):
    """pydantic 메시지를 한 줄로 정리해서 내려준다. 화면에는 입력 아래 한 줄만 보여준다."""
    first = exc.errors()[0] if exc.errors() else {}
    msg = str(first.get("msg", "입력을 확인해줘"))
    if msg.startswith("Value error, "):
        msg = msg[len("Value error, ") :]
    return JSONResponse(status_code=422, content={"detail": msg})


@app.get("/api/health")
def health():
    return {"ok": True}
