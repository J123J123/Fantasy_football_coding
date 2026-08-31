"""Configuration loaded without ever persisting credentials."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path("data")
    timeout: float = 20.0
    request_delay: float = 0.35
    game_id: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    refresh_token: str | None = None

    @property
    def oauth_configured(self) -> bool:
        return bool(self.client_id and self.client_secret and self.refresh_token)


def load_settings(data_dir: Path | None = None) -> Settings:
    load_dotenv()
    return Settings(
        data_dir=data_dir or Path(os.getenv("YAHOO_DATA_DIR", "data")),
        timeout=float(os.getenv("YAHOO_TIMEOUT", "20")),
        request_delay=float(os.getenv("YAHOO_REQUEST_DELAY", "0.35")),
        game_id=os.getenv("YAHOO_GAME_ID") or None,
        client_id=os.getenv("YAHOO_CLIENT_ID") or None,
        client_secret=os.getenv("YAHOO_CLIENT_SECRET") or None,
        refresh_token=os.getenv("YAHOO_REFRESH_TOKEN") or None,
    )
