"""Offline tests for the data layer, run against the recorded fixture."""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import mlb_data  # noqa: E402

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "gamelog_2026.json"


def load_log():
    return mlb_data.parse_game_log(json.loads(FIXTURE.read_text()))


def test_parse_game_log_shape():
    log = load_log()
    assert len(log) == 25
    assert list(log.columns) == mlb_data.GAME_LOG_COLUMNS
    assert log["date"].is_monotonic_increasing
    assert log["team"].unique().tolist() == ["PHI"]


def test_last_ten_games_window():
    log = load_log()
    window = mlb_data.last_n_games(log, 10)
    assert len(window) == 10
    assert window["date"].iloc[-1] == log["date"].iloc[-1]
    assert window["game_pk"].tolist() == log["game_pk"].tolist()[-10:]


def test_window_average_matches_hits_over_at_bats():
    window = mlb_data.last_n_games(load_log(), 10)
    summary = mlb_data.summarize(window)
    assert summary["games"] == 10
    assert summary["ab"] == int(window["ab"].sum())
    assert summary["h"] == int(window["h"].sum())
    assert summary["avg"] == summary["h"] / summary["ab"]
    assert 0.0 <= summary["avg"] <= 1.0


def test_summarize_handles_empty_window():
    empty = mlb_data.last_n_games(load_log().iloc[0:0], 10)
    summary = mlb_data.summarize(empty)
    assert summary["games"] == 0
    assert summary["avg"] is None


def test_cumulative_average_ends_at_window_average():
    window = mlb_data.with_trend_columns(mlb_data.last_n_games(load_log(), 10))
    summary = mlb_data.summarize(window)
    assert window["cum_avg"].iloc[-1] == summary["avg"]
    assert window["cum_ab"].iloc[-1] == summary["ab"]


def test_rolling_average_uses_prior_games():
    log = load_log()
    rolling = mlb_data.rolling_average(log, window=10, tail=10)
    assert len(rolling) == 10
    # Every plotted point has a full ten games behind it in this fixture.
    assert (rolling["roll_ab"] > 0).all()
    last = rolling.iloc[-1]
    window = mlb_data.last_n_games(log, 10)
    assert last["roll_h"] == int(window["h"].sum())
    assert last["roll_ab"] == int(window["ab"].sum())


def test_rolling_average_drops_incomplete_windows():
    """A ten-game average is never plotted from fewer than ten games."""
    log = load_log().tail(4).reset_index(drop=True)
    assert mlb_data.rolling_average(log, window=10, tail=10).empty

    log = load_log().tail(12).reset_index(drop=True)
    rolling = mlb_data.rolling_average(log, window=10, tail=10)
    assert len(rolling) == 3  # games 10, 11 and 12 each have ten behind them
    assert (rolling["roll_ab"] == [
        int(log["ab"][i - 9 : i + 1].sum()) for i in (9, 10, 11)
    ]).all()


def test_batting_average_guards_zero_at_bats():
    assert mlb_data.batting_average(0, 0) is None
    assert mlb_data.batting_average(1, 4) == 0.25


def test_format_avg():
    assert mlb_data.format_avg(0.3125) == ".313"
    assert mlb_data.format_avg(1.0) == "1.000"
    assert mlb_data.format_avg(None) == "—"


def test_current_season_rolls_back_in_the_offseason():
    import datetime as dt

    assert mlb_data.current_season(dt.date(2026, 8, 31)) == 2026
    assert mlb_data.current_season(dt.date(2027, 1, 15)) == 2026
    assert mlb_data.current_season(dt.date(2027, 4, 1)) == 2027


def test_summarize_returns_the_same_keys_empty_or_not():
    log = load_log()
    filled = mlb_data.summarize(mlb_data.last_n_games(log, 10))
    empty = mlb_data.summarize(log.iloc[0:0])
    assert set(filled) == set(empty)
    for stat in mlb_data.COUNTING_STATS:
        assert empty[stat] == 0
