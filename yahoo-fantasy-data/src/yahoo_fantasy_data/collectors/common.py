from __future__ import annotations

from typing import Any

from ..config import Settings
from ..utils import entity_objects, first_value, flatten, stable_frame, stat_columns
from ..yahoo import league_key


def context_row(season: int, league_id: str, week: int, game_id: str) -> dict[str, Any]:
    return {"season": season, "week": week, "game_id": game_id, "league_id": str(league_id), "league_key": league_key(game_id, str(league_id))}


def resolve(season: int, league_id: str, week: int, settings: Settings | None, game_id: str | None, provider: Any | None):
    if game_id and provider:
        return settings, provider, game_id, league_key(game_id, league_id)
    from ..yahoo import _context
    return (*_context(season, league_id, settings),)  # settings, provider, game id, key


def player_rows(payload: Any, base: dict[str, Any], projected: bool = False) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for player in entity_objects(payload, "player_key"):
        flat = flatten(player)
        row = {**base, **flat}
        row["player_id"] = player.get("player_id") or str(player["player_key"]).split(".")[-1]
        row["player_key"] = player["player_key"]
        row["player_name"] = first_value(player.get("name", {}), "full") or first_value(player, "name")
        row["nfl_team"] = player.get("editorial_team_abbr") or player.get("nfl_team")
        row["position"] = player.get("primary_position") or player.get("position")
        eligible = player.get("eligible_positions")
        row["eligible_positions"] = ",".join(map(str, eligible)) if isinstance(eligible, list) else eligible
        row["status"] = player.get("status")
        row["injury_status"] = player.get("injury_note") or player.get("injury_status")
        row["bye_week"] = first_value(player, "bye_weeks") or player.get("bye_week")
        row["percent_owned"] = first_value(player, "percent_owned")
        row["percent_started"] = first_value(player, "percent_started")
        stats = stat_columns(player, "projected_" if projected else "")
        row.update(stats)
        # Yahoo varies here; retain an explicitly supplied points value too.
        points = first_value(player, "fantasy_points") or first_value(player, "total")
        # The collection endpoint can silently return season totals. Do not label
        # those as weekly actuals when Yahoo did not honour the requested week.
        coverage = first_value(player, "coverage_type")
        row["projected_points" if projected else "fantasy_points_actual"] = points if projected or coverage == "week" else None
        rows.append(row)
    return rows
