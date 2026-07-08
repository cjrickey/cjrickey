"""
Verifies Clerk session tokens on incoming requests, replacing the old
shared-bearer-token scheme now that this is a real multi-tenant, paid
product -- every request needs to be tied to a specific signed-in user,
not just "has the shared secret."

The frontend (via @clerk/nextjs) attaches the signed-in user's session
token as `Authorization: Bearer <token>`. Clerk signs these as RS256 JWTs;
we verify the signature against Clerk's public JWKS (fetched once, cached
in memory) rather than calling Clerk's API on every request.

Requires CLERK_ISSUER (e.g. "https://your-app.clerk.accounts.dev", found
in the Clerk dashboard under API Keys / JWT templates). There is no
no-auth fallback here -- unlike the old API_AUTH_TOKEN, which was
optional for a single-operator tool, a paid multi-tenant product always
needs to know who's calling.
"""
import os
import time
from typing import Optional

import jwt
import requests
from fastapi import Header, HTTPException

CLERK_ISSUER = os.environ.get("CLERK_ISSUER")

_jwks_cache: dict = {"keys": None, "fetched_at": 0.0}
_JWKS_TTL_SECONDS = 3600


def _get_jwks() -> dict:
    now = time.time()
    if _jwks_cache["keys"] is None or now - _jwks_cache["fetched_at"] > _JWKS_TTL_SECONDS:
        resp = requests.get(f"{CLERK_ISSUER}/.well-known/jwks.json", timeout=5)
        resp.raise_for_status()
        _jwks_cache["keys"] = resp.json()
        _jwks_cache["fetched_at"] = now
    return _jwks_cache["keys"]


def _verify(token: str) -> dict:
    unverified_header = jwt.get_unverified_header(token)
    kid = unverified_header.get("kid")

    jwks = _get_jwks()
    matching = [k for k in jwks.get("keys", []) if k.get("kid") == kid]
    if not matching:
        # kid rotated since our cache was fetched -- refetch once before giving up
        _jwks_cache["keys"] = None
        jwks = _get_jwks()
        matching = [k for k in jwks.get("keys", []) if k.get("kid") == kid]
        if not matching:
            raise HTTPException(401, "Unknown signing key")

    public_key = jwt.algorithms.RSAAlgorithm.from_jwk(matching[0])
    try:
        return jwt.decode(
            token,
            key=public_key,
            algorithms=["RS256"],
            issuer=CLERK_ISSUER,
            options={"verify_aud": False},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(401, f"Invalid session token: {exc}") from exc


def require_user(authorization: Optional[str] = Header(default=None)) -> str:
    """FastAPI dependency: returns the Clerk user id (the `sub` claim), or
    raises 401. Use this (not require_auth) on any endpoint that touches
    user-owned data."""
    if CLERK_ISSUER is None:
        raise HTTPException(500, "Server is missing CLERK_ISSUER")
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing session token")

    token = authorization.removeprefix("Bearer ")
    claims = _verify(token)
    return claims["sub"]
