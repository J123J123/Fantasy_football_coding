"""Historical Yahoo projection collector; it never falls back to HTML."""
from __future__ import annotations

from typing import Any
import pandas as pd

from .common import context_row, player_rows, resolve
from ..config import Settings
from ..errors import YahooProjectionUnavailableError
from ..providers.projections import ProjectionProvider
from ..utils import stable_frame


def get_projection_data(season: int, league_id: str, week: int, *, settings: Settings | None = None, game_id: str | None = None, provider: Any | None = None) -> pd.DataFrame:
    settings, provider, game_id, key = resolve(season, league_id, week, settings, game_id, provider)
    projection_provider = ProjectionProvider(provider)
    base = context_row(season, league_id, week, game_id)
    records: list[dict[str, Any]] = []
    start, page_size = 0, 25
    while True:
        payload = projection_provider.players(key, week, start, page_size)
        page = player_rows(payload, base, projected=True)
        records.extend(page)
        if len(page) < page_size:
            break
        start += page_size
    frame = stable_frame(records, ["player_id"])
    # A successful player endpoint is not proof of historical projections: Yahoo
    # can return season actuals while ignoring projection parameters.
    if frame.empty or "projected_points" not in frame or frame["projected_points"].notna().sum() == 0:
        raise YahooProjectionUnavailableError(
            f"Yahoo returned no individual projected points for historical week {week}; no substitute was written."
        )
    return frame
