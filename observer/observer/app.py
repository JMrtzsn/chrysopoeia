import os
from collections.abc import Callable
from datetime import datetime, timezone

from fastapi import FastAPI, Response
from fastapi.responses import JSONResponse
from google.api_core.exceptions import GoogleAPIError

from observer.health import query_health
from observer.insights import BigQueryClient, query_insights


def create_app(
    *,
    table: str | None = None,
    client: BigQueryClient | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> FastAPI:
    app = FastAPI(title="Chrysopoeia Observer")

    # Cloud Run's front end reserves /healthz, so it never reaches the container.
    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/insights")
    def insights() -> Response:
        try:
            result = query_insights(clock(), table=table, client=client)
        except (GoogleAPIError, OSError, TimeoutError, ValueError):
            return Response(status_code=503)
        return JSONResponse(result)

    @app.get("/v1/health")
    def journey_health() -> Response:
        try:
            result = query_health(clock(), table=table, client=client)
        except (GoogleAPIError, OSError, TimeoutError, ValueError):
            return Response(status_code=503)
        return JSONResponse(result)

    return app


app = create_app(table=os.environ.get("OBSERVER_ARCHIVE_TABLE"))
