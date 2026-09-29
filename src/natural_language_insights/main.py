import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException

from natural_language_insights import jobs
from natural_language_insights.api.routes.conversations import router as conversations_router
from natural_language_insights.api.routes.datasets import router as datasets_router
from natural_language_insights.api.routes.jobs import router as jobs_router
from natural_language_insights.config.settings import settings
from natural_language_insights.database import database, init_schema

logger = logging.getLogger(__name__)

STATIC_DIRECTORY = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.connect()
    init_schema()
    yield
    jobs.executor.shutdown(wait=True, cancel_futures=True)
    database.close()


def error_response(status_code: int, code: str, message) -> JSONResponse:
    return JSONResponse(
        status_code=status_code, content={"error": {"code": code, "message": message}}
    )


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        return error_response(exc.status_code, "http_error", exc.detail)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return error_response(422, "validation_error", jsonable_errors(exc))

    @app.exception_handler(Exception)
    async def unhandled_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return error_response(500, "internal_error", "Internal server error.")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", include_in_schema=False)
    def ui() -> FileResponse:
        return FileResponse(STATIC_DIRECTORY / "index.html")

    app.include_router(datasets_router)
    app.include_router(jobs_router)
    app.include_router(conversations_router)
    return app


def jsonable_errors(exc: RequestValidationError) -> list[dict]:
    return [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]


app = create_app()
