"""Fantasy matchup schedule; intentionally separate from roster snapshots."""
from __future__ import annotations

from typing import Any
import pandas as pd

from .common import context_row, resolve
from ..config import Settings
from ..utils import entity_objects, first_value, flatten, stable_frame


def get_schedule(season: int, league_id: str, week: int, *, settings: Settings | None = None, game_id: str | None = None, provider: Any | None = None) -> pd.DataFrame:
    settings, provider, game_id, key = resolve(season, league_id, week, settings, game_id, provider)
    payload = provider.scoreboard(key, week)
    records: list[dict[str, Any]] = []
    for matchup in entity_objects(payload, "matchup_id"):
        teams = entity_objects(matchup, "team_key")
        if not teams:
            continue
        for index, team in enumerate(teams[:2]):
            opponent = teams[1 - index] if len(teams) == 2 else {}
            records.append({
                **context_row(season, league_id, week, game_id), **flatten(matchup),
                "matchup_id": matchup.get("matchup_id"), "team_id": team.get("team_id") or str(team["team_key"]).split(".")[-1],
                "team_key": team["team_key"], "team_name": first_value(team.get("name", {}), "") or team.get("name"),
                "opponent_team_id": opponent.get("team_id") or (str(opponent.get("team_key", "")).split(".")[-1] or None),
                "opponent_team_key": opponent.get("team_key"), "opponent_team_name": first_value(opponent.get("name", {}), "") or opponent.get("name"),
                "is_home": bool(index == 0), "is_playoffs": matchup.get("is_playoffs"), "is_consolation": matchup.get("is_consolation"),
                "team_actual_points": first_value(team, "team_points"), "opponent_actual_points": first_value(opponent, "team_points"),
                "winner_team_id": matchup.get("winner_team_key"), "is_tied": matchup.get("is_tied"), "status": matchup.get("status"),
            })
    return stable_frame(records, ["week", "team_id"])
