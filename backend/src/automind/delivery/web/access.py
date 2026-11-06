"""Access before any external demo (no accounts yet): an anonymous owner per browser, same-site requests only.

- Owner: a random token in an HttpOnly cookie; the server keeps only its SHA-256. A chat belongs to the owner that
  created it; another browser gets "not found" for it (REST 404, WebSocket close 4404) and never sees it listed.
  A chat created before owners existed is claimed by the first browser that opens it.
- Origin: a browser request from another site (WebSocket handshake, or a change: POST/PATCH/PUT/DELETE) is refused.
  Same host, or one of `allowed_origins` (the Vite dev server). No Origin header (curl, tests) is not a browser.
- Admin: internal endpoints need `Authorization: Bearer <ADMIN_TOKEN>`, or a request from this machine when no
  token is set.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from collections.abc import Iterable
from urllib.parse import urlsplit

COOKIE = "automind_owner"
MAX_AGE = 400 * 24 * 3600  # the longest browsers keep a cookie
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{32,64}$")
CHANGES = ("POST", "PATCH", "PUT", "DELETE")
LOOPBACK = ("127.0.0.1", "::1", "localhost")


def new_token() -> str:
    return secrets.token_urlsafe(32)


def owner_of(token: str | None) -> str | None:
    """The stored owner id for a cookie value; None for a missing or malformed cookie."""
    if not token or not _TOKEN.match(token):
        return None
    return hashlib.sha256(token.encode()).hexdigest()


def origin_ok(origin: str | None, host: str | None, allowed: Iterable[str]) -> bool:
    if not origin:
        return True
    if origin.rstrip("/") in {a.rstrip("/") for a in allowed}:
        return True
    netloc = urlsplit(origin).netloc
    return bool(host) and netloc.lower() == (host or "").lower()


def admin_ok(authorization: str | None, client_host: str | None, token: str | None) -> bool:
    if token:
        given = (authorization or "").removeprefix("Bearer ").strip()
        return hmac.compare_digest(given.encode(), token.encode())
    return (client_host or "") in LOOPBACK


def cookie_header(token: str, secure: bool) -> str:
    return (f"{COOKIE}={token}; Path=/; Max-Age={MAX_AGE}; HttpOnly; SameSite=Lax"
            + ("; Secure" if secure else ""))  # fmt: skip
