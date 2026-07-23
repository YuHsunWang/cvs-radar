"""Authentication helpers for privileged API capabilities."""

from __future__ import annotations

import os
import secrets

from fastapi import HTTPException

API_TOKEN_ENV_VAR = "CVS_RADAR_API_TOKEN"


def require_privileged_access(requested: bool, supplied_token: str | None) -> bool:
    """Return whether access was granted, rejecting unsafe privileged requests."""
    if not requested:
        return False

    configured_token = os.environ.get(API_TOKEN_ENV_VAR, "").strip()
    if not configured_token:
        raise HTTPException(status_code=403, detail="privileged API capabilities are disabled")
    if supplied_token is None or not secrets.compare_digest(supplied_token, configured_token):
        raise HTTPException(status_code=401, detail="invalid or missing API token")
    return True
