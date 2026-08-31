from __future__ import annotations

from yahoo_fantasy_data.collectors.league_settings import parse_settings
from yahoo_fantasy_data.collectors.players import get_player_data
from yahoo_fantasy_data.collectors.teams import get_team_data


class FakeProvider:
    def __init__(self) -> None:
        self.weeks: list[int] = []

    def players(self, key: str, week: int, start: int, count: int, projected: bool = False):
        self.weeks.append(week)
        if start:
            return {"players": []}
        return {"players": {"0": {"player_key": "461.p.7", "player_id": "7", "name": {"full": "Test Player"}, "primary_position": "QB"}, "count": 1}}

    def teams_roster(self, key: str, week: int):
        self.weeks.append(week)
        return {"teams": {"0": {"team_key": "461.l.1.t.1", "team_id": "1", "name": "A", "roster": {"players": {"0": {"player_key": "461.p.7", "selected_position": {"position": "BN"}, "name": {"full": "Test Player"}}}}}}}


def test_player_pagination_and_week_are_preserved() -> None:
    provider = FakeProvider()
    frame = get_player_data(2025, "1", 5, game_id="461", provider=provider)
    assert len(frame) == 1
    assert frame.loc[0, "week"] == 5
    assert provider.weeks == [5]


def test_roster_slot_parsing_and_historical_week() -> None:
    provider = FakeProvider()
    frame = get_team_data(2025, "1", 10, game_id="461", provider=provider)
    assert frame.loc[0, "roster_slot"] == "BN"
    assert not frame.loc[0, "is_starting"]
    assert provider.weeks == [10]


def test_scoring_and_roster_settings_are_tabular() -> None:
    rows = parse_settings({"roster_positions": {"0": {"position": "QB", "count": 1}}, "stat_categories": {"0": {"stat_id": "4", "name": "Passing Yards", "value": "0.04"}}}, {"season": 2025})
    assert any(row["setting_type"] == "roster_position" and row["position"] == "QB" for row in rows)
    assert any(row["setting_type"] == "scoring_stat" and row["stat_id"] == "4" for row in rows)


class PagedProvider(FakeProvider):
    def __init__(self) -> None:
        super().__init__()
        self.starts: list[int] = []

    def players(self, key: str, week: int, start: int, count: int, projected: bool = False):
        self.weeks.append(week)
        self.starts.append(start)
        size = 25 if start == 0 else 1
        return {"players": {str(index): {"player_key": f"461.p.{start + index}", "player_id": str(start + index), "name": {"full": f"Player {start + index}"}} for index in range(size)}}


def test_player_pagination_requests_the_next_offset() -> None:
    provider = PagedProvider()
    frame = get_player_data(2025, "1", 5, game_id="461", provider=provider)
    assert len(frame) == 26
    assert provider.starts == [0, 25]
