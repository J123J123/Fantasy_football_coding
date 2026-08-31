"""HTTP access and snapshot orchestration."""
from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import time
from typing import Any, Callable

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import Settings, load_settings
from .errors import (
    YahooAPIError,
    YahooAuthenticationError,
    YahooNotFoundError,
    YahooPrivateLeagueError,
    YahooRateLimitError,
)
from .utils import first_value

PUBLIC_BASE_URL = "https://pub-api-ro.fantasysports.yahoo.com/fantasy/v2"
OFFICIAL_BASE_URL = "https://fantasysports.yahooapis.com/fantasy/v2"
USER_AGENT = "yahoo-fantasy-data/0.1 (public data archiver; contact: repository owner)"


class YahooHTTPClient:
    """Small, polite client shared by providers."""

    def __init__(self, settings: Settings, session: requests.Session | None = None) -> None:
        self.settings = settings
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
        retry = Retry(total=2, backoff_factor=0.6, status_forcelist=(429, 500, 502, 503, 504), allowed_methods=("GET",))
        self.session.mount("https://", HTTPAdapter(max_retries=retry))

    def get(self, path: str, *, params: dict[str, Any] | None = None, token: str | None = None, official: bool = False) -> dict[str, Any]:
        base = OFFICIAL_BASE_URL if official else PUBLIC_BASE_URL
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        try:
            response = self.session.get(f"{base}/{path.lstrip('/')}", params=params, headers=headers, timeout=self.settings.timeout)
        except requests.RequestException as error:
            raise YahooAPIError(f"Yahoo request failed for {path}: {error}") from error
        if response.status_code in (401, 403):
            raise YahooAuthenticationError(f"Yahoo requires authentication for {path}.")
        if response.status_code == 404:
            raise YahooNotFoundError(f"Yahoo resource was not found: {path}")
        if response.status_code == 429:
            raise YahooRateLimitError("Yahoo rate limited the request; retry later.")
        if response.status_code >= 400:
            raise YahooAPIError(f"Yahoo returned HTTP {response.status_code} for {path}: {response.text[:240]}")
        try:
            return response.json()
        except ValueError as error:
            raise YahooAPIError(f"Yahoo returned non-JSON data for {path}.") from error


def get_game_id(season: int, *, provider: Any | None = None, settings: Settings | None = None) -> str:
    """Discover the NFL game id for a season, with an explicit environment fallback."""
    active_settings = settings or load_settings()
    if active_settings.game_id:
        return active_settings.game_id
    if provider is None:
        from .providers.public import PublicYahooProvider
        provider = PublicYahooProvider(YahooHTTPClient(active_settings))
    payload = provider.games(season)
    for candidate in (item for item in _walk_values(payload) if isinstance(item, dict)):
        season_value = candidate.get("season")
        game_key = candidate.get("game_key") or candidate.get("game_id")
        code = candidate.get("code") or candidate.get("game_code")
        if str(season_value) == str(season) and str(code).lower() in {"nfl", "football"} and game_key:
            return str(game_key).split(".")[0]
    game_id = first_value(payload, "game_id")
    if game_id is not None:
        return str(game_id)
    raise YahooNotFoundError(f"Yahoo did not expose an NFL game id for season {season}; supply YAHOO_GAME_ID.")


def _walk_values(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_values(child)


def league_key(game_id: str, league_id: str) -> str:
    return f"{game_id}.l.{league_id}"


def _context(season: int, league_id: str, settings: Settings | None = None) -> tuple[Settings, Any, str, str]:
    active_settings = settings or load_settings()
    from .providers.public import PublicYahooProvider
    public = PublicYahooProvider(YahooHTTPClient(active_settings))
    game_id = get_game_id(season, provider=public, settings=active_settings)
    return active_settings, public, game_id, league_key(game_id, str(league_id))


def league_metadata(season: int, league_id: str, settings: Settings | None = None) -> tuple[dict[str, Any], Settings, Any, str, str]:
    active_settings, public, game_id, key = _context(season, league_id, settings)
    payload = public.league(key)
    private = first_value(payload, "is_private")
    league_type = first_value(payload, "league_type")
    if str(private).lower() in {"1", "true"} or str(league_type).lower() == "private":
        raise YahooPrivateLeagueError(f"League {key} is private and will not be archived.")
    return payload, active_settings, public, game_id, key


def _snapshot_path(settings: Settings, league_id: str, season: int, data_type: str, week: int) -> Path:
    return settings.data_dir / str(league_id) / str(season) / data_type / f"{data_type}_week_{week}.csv.gz"


def write_snapshot(frame: pd.DataFrame, path: Path, overwrite: bool) -> str:
    if path.exists() and not overwrite:
        return "skipped_existing"
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, compression="gzip")
    return "written"


def _metadata_path(settings: Settings, league_id: str, season: int) -> Path:
    return settings.data_dir / str(league_id) / str(season) / "metadata.json"


def update_metadata(settings: Settings, season: int, league_id: str, game_id: str, key: str, payload: Any, week: int, statuses: dict[str, str]) -> None:
    path = _metadata_path(settings, league_id, season)
    path.parent.mkdir(parents=True, exist_ok=True)
    old: dict[str, Any] = json.loads(path.read_text()) if path.exists() else {}
    end_week = first_value(payload, "end_week") or old.get("end_week")
    metadata = {
        **old,
        "season": season, "game_id": game_id, "league_id": str(league_id), "league_key": key,
        "league_name": first_value(payload, "name", old.get("league_name")),
        "league_type": "public", "start_week": first_value(payload, "start_week", old.get("start_week", 1)),
        "end_week": end_week, "last_collected_week": max(week, int(old.get("last_collected_week", 0))),
        "last_updated": datetime.now(UTC).isoformat(),
        "sources": {**old.get("sources", {}), **statuses},
    }
    path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")


def collect_week(season: int, league_id: str, week: int, overwrite: bool = False, *, settings: Settings | None = None) -> dict[str, str]:
    """Collect independent datasets, retaining successes when another endpoint fails."""
    if week < 1:
        raise ValueError("week must be at least 1")
    payload, active_settings, _public, game_id, key = league_metadata(season, league_id, settings)
    from .collectors import draft, league_settings, players, projections, schedule, teams
    jobs: dict[str, tuple[str, Callable[..., pd.DataFrame]]] = {
        "player_data": ("player_data", players.get_player_data),
        "projection_data": ("projection_data", projections.get_projection_data),
        "team_data": ("team_data", teams.get_team_data),
        "schedule": ("schedule", schedule.get_schedule),
        "draft": ("draft", draft.get_draft_data),
        "league_settings": ("league_settings", league_settings.get_league_settings),
    }
    statuses: dict[str, str] = {}
    for name, (folder, collector) in jobs.items():
        path = _snapshot_path(active_settings, league_id, season, folder, week)
        if path.exists() and not overwrite:
            statuses[name] = "skipped_existing"
            continue
        try:
            frame = collector(season, str(league_id), week, settings=active_settings, game_id=game_id, provider=_public)
            statuses[name] = write_snapshot(frame, path, overwrite=True)
        except YahooAuthenticationError:
            statuses[name] = "authentication_required"
        except Exception as error:  # each collector is deliberately isolated
            statuses[name] = f"failed: {type(error).__name__}: {error}"
        time.sleep(active_settings.request_delay)
    update_metadata(active_settings, season, str(league_id), game_id, key, payload, week, statuses)
    return statuses


def backfill_season(season: int, league_id: str, start_week: int = 1, end_week: int | None = None, overwrite: bool = False, *, settings: Settings | None = None) -> dict[int, dict[str, str]]:
    payload, active_settings, _public, _game_id, _key = league_metadata(season, league_id, settings)
    resolved_end = end_week or int(first_value(payload, "end_week", start_week))
    if resolved_end < start_week:
        raise ValueError("end_week must not precede start_week")
    return {week: collect_week(season, league_id, week, overwrite, settings=active_settings) for week in range(start_week, resolved_end + 1)}
