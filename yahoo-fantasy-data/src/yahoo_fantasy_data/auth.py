"""Minimal OAuth refresh-token support for the official API."""
from __future__ import annotations

from typing import Any
import requests

from .config import Settings
from .errors import YahooAuthenticationError

TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"


def refresh_access_token(settings: Settings, session: requests.Session | None = None) -> str:
    if not settings.oauth_configured:
        raise YahooAuthenticationError(
            "OAuth is required for this Yahoo endpoint. Set YAHOO_CLIENT_ID, "
            "YAHOO_CLIENT_SECRET, and YAHOO_REFRESH_TOKEN in your environment or .env."
        )
    response = (session or requests.Session()).post(
        TOKEN_URL,
        auth=(settings.client_id, settings.client_secret),
        data={"grant_type": "refresh_token", "refresh_token": settings.refresh_token},
        timeout=settings.timeout,
    )
    if response.status_code in (401, 403):
        raise YahooAuthenticationError("Yahoo rejected the configured OAuth credentials.")
    response.raise_for_status()
    payload: dict[str, Any] = response.json()
    token = payload.get("access_token")
    if not isinstance(token, str):
        raise YahooAuthenticationError("Yahoo OAuth response contained no access token.")
    return token
