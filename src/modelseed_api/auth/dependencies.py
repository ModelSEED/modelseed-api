"""Authentication dependencies for FastAPI.

Extracts and validates PATRIC/RAST tokens from request headers.
Both auth methods go through the nexus_emulation service (OAuth1).
The token is passed through to the Workspace service for validation.
"""

import logging
from dataclasses import dataclass

from fastapi import HTTPException, Request

from modelseed_api.config import settings

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

    Some tokens include '@patricbrc.org' in the username field
    (e.g. 'un=seaver@patricbrc.org'), but workspace paths use the bare
    username ('/seaver/modelseed/'). Strip the suffix to avoid path mismatches.
    """
    for part in token.split("|"):
        if part.startswith("un="):
            username = part[3:]
            # Strip email-style suffixes — workspace paths use bare usernames
            for suffix in ("@patricbrc.org", "@rast.nmpdr.org"):
                if username.endswith(suffix):
                    username = username[: -len(suffix)]
                    break
            return username
    # Fallback: try to extract from other formats
    raise HTTPException(
        status_code=401,
        detail="Could not extract username from token",
    )


async def get_current_user(request: Request) -> AuthUser:
    """FastAPI dependency that extracts the authenticated user from request headers.

    The frontend sends the token as either 'Authorization' or 'Authentication' header.
    We support both for backward compatibility.

    When storage_backend == "local", authentication is relaxed: any token is
    accepted (username extracted if possible), and requests without a token
    default to user "local".
    """
    token = request.headers.get("Authorization") or request.headers.get("Authentication")

    # Local storage mode: relax auth requirements
    if settings.storage_backend == "local":
        username = "local"
        if token:
            token = token.removeprefix("Bearer ").strip('"').strip("'")
            try:
                username = _extract_username(token)
            except HTTPException:
                pass
        else:
            token = "local-dev-token"
        return AuthUser(username=username, token=token)

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
