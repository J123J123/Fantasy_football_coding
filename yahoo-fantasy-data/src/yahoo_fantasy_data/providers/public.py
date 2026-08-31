"""Anonymous, read-only Yahoo Fantasy provider."""
from __future__ import annotations

from typing import Any

from ..yahoo import YahooHTTPClient


class PublicYahooProvider:
    """Use the unofficial public endpoint first; it deliberately sends no cookies."""

    source_name = "public_internal"

    def __init__(self, client: YahooHTTPClient) -> None:
        self.client = client

    def get(self, path: str, **params: Any) -> dict[str, Any]:
        return self.client.get(path, params={"format": "json", **params})

    def games(self, season: int) -> dict[str, Any]:
        return self.get("games", game_codes="nfl", seasons=str(season))

    def league(self, league_key: str) -> dict[str, Any]:
        return self.get(f"league/{league_key}")

    def players(self, league_key: str, week: int, start: int, count: int, projected: bool = False) -> dict[str, Any]:
        extras = ";out=stats" if not projected else ";out=stats"
        path = f"league/{league_key}/players;start={start};count={count};week={week}{extras}"
        params: dict[str, Any] = {"week": week}
        if projected:
            params.update(show_projected_stats=1, show_live_projected_points=1)
        return self.get(path, **params)

    def teams_roster(self, league_key: str, week: int) -> dict[str, Any]:
        return self.get(f"league/{league_key}/teams/roster;week={week}", week=week)

    def scoreboard(self, league_key: str, week: int) -> dict[str, Any]:
        return self.get(f"league/{league_key}/scoreboard;week={week}", week=week)

    def draft(self, league_key: str) -> dict[str, Any]:
        return self.get(f"league/{league_key}/draftresults")

    def settings(self, league_key: str) -> dict[str, Any]:
        return self.get(f"league/{league_key}/settings")
