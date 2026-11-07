"""HTTP layer. Routes stay thin and delegate to app.recommender."""

import logging
import re
import sqlite3
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Path, Query, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

from app import config, db, repository
from app.models import RecommendationResponse
from app.recommender import UserNotFoundError, recommend

logger = logging.getLogger("app")

# Accept a caller's request id only if it is short and plain, so it can't inject into logs.
_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def configure_logging() -> None:
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)
    logger.setLevel(config.LOG_LEVEL)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    if not config.DB_PATH.exists():
        # Not fatal, so the process can start before the seed job runs. /ready reports it.
        logger.warning("Database not found at %s. Run `python -m app.seed`.", config.DB_PATH)
    yield


app = FastAPI(
    title="Lean In Circle Recommendations",
    description="Ranked Circles a member should join, each with a member facing explanation.",
    version=config.API_VERSION,
    lifespan=lifespan,
)


@app.middleware("http")
async def request_context(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    """Tag every request with an id and log its method, path, status and latency."""
    incoming = request.headers.get("X-Request-ID", "")
    request_id = incoming if _REQUEST_ID.match(incoming) else uuid.uuid4().hex
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("Unhandled error request_id=%s path=%s", request_id, request.url.path)
        raise
    elapsed_ms = (time.perf_counter() - start) * 1000
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "%s %s %d %.1fms request_id=%s",
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
        request_id,
    )
    return response


@app.exception_handler(UserNotFoundError)
async def user_not_found(_: Request, exc: UserNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(sqlite3.DatabaseError)
async def database_error(_: Request, exc: sqlite3.DatabaseError) -> JSONResponse:
    # Details go to the log, never to the client.
    logger.error("Database error: %s", exc, exc_info=exc)
    return JSONResponse(status_code=503, content={"detail": "Database unavailable"})


def get_db() -> Iterator[sqlite3.Connection]:
    """One read only connection per request. SQLite connections are cheap to open."""
    if not config.DB_PATH.exists():
        raise HTTPException(503, "Database not initialized")
    conn = db.connect(config.DB_PATH, read_only=True)
    try:
        yield conn
    finally:
        conn.close()


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse("/docs")


@app.get("/health", summary="Liveness check")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready", summary="Readiness check, verifies the database is seeded")
def ready(conn: sqlite3.Connection = Depends(get_db)) -> dict[str, str]:
    try:
        repository.ping(conn)
    except RuntimeError as exc:
        raise HTTPException(503, "Database not initialized") from exc
    return {"status": "ok"}


@app.get(
    "/users/{user_id}/recommendations",
    response_model=RecommendationResponse,
    # exclude_unset rather than exclude_none. It drops score, debug and hint when they weren't
    # set, but keeps meaningful nulls such as an uncapped max_members or a missing topic.
    response_model_exclude_unset=True,
    summary="Recommend Circles for a member to join",
    responses={404: {"description": "User not found"}, 503: {"description": "Database unavailable"}},
)
def get_recommendations(
    user_id: int = Path(ge=1),
    limit: int = Query(config.DEFAULT_LIMIT, ge=1, le=config.MAX_LIMIT),
    debug: bool = Query(False, description="Include score breakdowns and excluded Circles"),
    conn: sqlite3.Connection = Depends(get_db),
) -> RecommendationResponse:
    return recommend(conn, user_id=user_id, limit=limit, debug=debug)
