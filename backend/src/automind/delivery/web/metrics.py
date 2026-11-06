"""GET /metrics for Prometheus (spec 010 FR-030, contracts/metrics.md).

With METRICS_TOKEN set, a matching bearer token is required; without it, only clients in METRICS_NETS (loopback and
the Docker network by default) may scrape. The response is built from memory only (FR-031).
"""

from __future__ import annotations

import hmac
import ipaddress

from fastapi import APIRouter, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from automind.shared.infrastructure.config.settings import settings
from automind.shared.infrastructure.metrics import prom  # noqa: F401 - registers the metric families

router = APIRouter()


def metrics_ok(authorization: str | None, client_host: str | None, token: str | None, nets: str) -> bool:
    if token:
        given = (authorization or "").removeprefix("Bearer ").strip()
        return hmac.compare_digest(given.encode(), token.encode())
    try:
        ip = ipaddress.ip_address((client_host or "").strip())
    except ValueError:
        return False
    for n in (x.strip() for x in nets.split(",") if x.strip()):
        try:
            if ip in ipaddress.ip_network(n, strict=False):
                return True
        except ValueError:
            continue
    return False


@router.get("/metrics", include_in_schema=False)
async def metrics(request: Request) -> Response:
    s = settings()
    host = request.client.host if request.client else None
    if not metrics_ok(request.headers.get("authorization"), host, s.metrics_token, s.metrics_nets):
        return Response(status_code=403, content="forbidden")
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
