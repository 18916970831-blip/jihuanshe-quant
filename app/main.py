import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.access import is_readonly
from app.config import STATIC_DIR
from app.routers import router
from app.services.bootstrap import bootstrap

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
TOKEN = os.environ.get("QUANT_API_TOKEN")
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    bootstrap()
    yield


app = FastAPI(title="集换社量化分析 Agent", lifespan=lifespan)
app.include_router(router)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def optional_token(request, call_next):
    if TOKEN and request.url.path.startswith("/api"):
        if request.headers.get("authorization") != f"Bearer {TOKEN}":
            return JSONResponse({"detail": "未授权"}, status_code=401)
    if request.method not in SAFE_METHODS and request.url.path.startswith("/api") and is_readonly(request):
        return JSONResponse({"detail": "分享页只能查看，不能修改数据。"}, status_code=403)
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static"):
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})
