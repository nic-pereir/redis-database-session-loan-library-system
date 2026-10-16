import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from api.deps import session_log
from api.v1.router import api_router
from app import cache
from app.crud import BusinessError

logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")

app = FastAPI(title="Library API", version="1.1.0")


@app.middleware("http")
async def lifecycle_log(request: Request, call_next):
    """Marca o início e o fim da requisição (só aparece com DEBUG_SESSION_LOG=true)."""
    session_log(f"REQUEST START {request.method} {request.url.path}")
    response = await call_next(request)
    session_log(f"REQUEST END   {request.method} {request.url.path} -> {response.status_code}")
    return response


@app.exception_handler(BusinessError)
def business_error_handler(request: Request, exc: BusinessError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


app.include_router(api_router, prefix="/api/v1")


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok", "redis": "up" if cache.ping() else "down"}
