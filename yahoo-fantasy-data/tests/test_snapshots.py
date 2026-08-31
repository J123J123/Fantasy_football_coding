from pathlib import Path

import pandas as pd

from yahoo_fantasy_data.config import Settings
from yahoo_fantasy_data.yahoo import _snapshot_path, write_snapshot


def test_exact_snapshot_filename_and_gzip_round_trip(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    path = _snapshot_path(settings, "707737", 2025, "player_data", 12)
    assert path.name == "player_data_week_12.csv.gz"
    frame = pd.DataFrame({"player_id": [1], "player_name": ["A"]})
    assert write_snapshot(frame, path, overwrite=False) == "written"
    assert pd.read_csv(path).to_dict("records") == [{"player_id": 1, "player_name": "A"}]


def test_existing_snapshot_is_immutable_by_default(tmp_path: Path) -> None:
    path = tmp_path / "x.csv.gz"
    write_snapshot(pd.DataFrame({"value": [1]}), path, overwrite=False)
    assert write_snapshot(pd.DataFrame({"value": [2]}), path, overwrite=False) == "skipped_existing"
    assert pd.read_csv(path).loc[0, "value"] == 1
