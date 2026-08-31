"""Complete league player-universe collector with conservative pagination."""
from __future__ import annotations

from typing import Any
import pandas as pd

from .common import context_row, player_rows, resolve
from ..config import Settings
from ..utils import stable_frame


def get_player_data(season: int, league_id: str, week: int, *, settings: Settings | None = None, game_id: str | None = None, provider: Any | None = None) -> pd.DataFrame:
    settings, provider, game_id, key = resolve(season, league_id, week, settings, game_id, provider)
    base = context_row(season, league_id, week, game_id)
    records: list[dict[str, Any]] = []
    start, page_size = 0, 25
    while True:
        payload = provider.players(key, week, start, page_size)
        page = player_rows(payload, base)
        records.extend(page)
        if len(page) < page_size:
            break
        start += page_size
    return stable_frame(records, ["player_id"])
