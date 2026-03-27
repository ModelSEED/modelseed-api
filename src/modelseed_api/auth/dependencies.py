"""Authentication dependencies for FastAPI.

Extracts and validates PATRIC/RAST tokens from request headers.
Both auth methods go through the nexus_emulation service (OAuth1).
The token is passed through to the Workspace service for validation.
"""

import logging
from dataclasses import dataclass

from fastapi import HTTPException, Request

logger = logging.getLogger("modelseed_api.auth")


@dataclass
class AuthUser:
    """Authenticated user context."""

    username: str
    token: str


def _extract_username(token: str) -> str:
    """Extract username from a PATRIC or RAST token.

    PATRIC tokens: 'un=username|tokenid=...|...'
    RAST tokens: contain 'rast.nmpdr.org', format varies but includes 'un=username|...'
    """
    for part in token.split("|"):
        if part.startswith("un="):
            return part[3:]
    # Fallback: try to extract from other formats
    raise HTTPException(
        status_code=401,
        detail="Could not extract username from token",
    )


async def get_current_user(request: Request) -> AuthUser:
    """FastAPI dependency that extracts the authenticated user from request headers.

    The frontend sends the token as either 'Authorization' or 'Authentication' header.
    We support both for backward compatibility.
    """
    token = request.headers.get("Authorization") or request.headers.get("Authentication")

    if not token:
        raise HTTPException(
            status_code=401,
            detail="Authentication required. Provide a PATRIC or RAST token in the Authorization header.",
        )

    # Strip 'Bearer ' prefix if present
    if token.startswith("Bearer "):
        token = token[7:]

    # Strip surrounding quotes if present (frontend sometimes wraps in quotes)
    token = token.strip('"').strip("'")

    username = _extract_username(token)
    token_type = "RAST" if "rast.nmpdr.org" in token else "PATRIC"
    logger.debug("Auth: un=%s (%s token)", username, token_type)
    return AuthUser(username=username, token=token)


async def get_optional_user(request: Request) -> AuthUser | None:
    """Like get_current_user but returns None instead of 401 for unauthenticated requests."""
    token = request.headers.get("Authorization") or request.headers.get("Authentication")
    if not token:
        return None
    try:
        return await get_current_user(request)
    except HTTPException:
        return None
