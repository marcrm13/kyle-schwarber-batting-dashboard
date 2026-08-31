"""Data access layer for the Kyle Schwarber batting dashboard.

Everything here talks to the public MLB Stats API (statsapi.mlb.com), which
needs no API key. Responses are cached in-process for a few minutes so a busy
dashboard does not hammer the upstream service.
"""

from __future__ import annotations

import datetime as dt
import threading
import time
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import pandas as pd
import requests

API_BASE = "https://statsapi.mlb.com/api/v1"

PLAYER_NAME = "Kyle Schwarber"
#: Schwarber's MLB people ID. Used when the name lookup is unavailable.
PLAYER_ID_FALLBACK = 656941

REQUEST_TIMEOUT = 15
REQUEST_RETRIES = 3
CACHE_TTL_SECONDS = 900

#: Columns of the game-log frame, in display order.
GAME_LOG_COLUMNS = [
    "date",
    "season",
    "game_pk",
    "team",
    "opponent",
    "home_away",
    "pa",
    "ab",
    "r",
    "h",
    "doubles",
    "triples",
    "hr",
    "rbi",
    "bb",
    "hbp",
    "so",
    "sf",
    "tb",
]


class MlbApiError(RuntimeError):
    """Raised when the MLB Stats API cannot be reached or returns junk."""


# --------------------------------------------------------------------------
# HTTP with a small TTL cache
# --------------------------------------------------------------------------

_cache: dict[tuple, tuple[float, Any]] = {}
_cache_lock = threading.Lock()


def _cache_key(path: str, params: dict[str, Any]) -> tuple:
    return (path, tuple(sorted(params.items())))


def _get(path: str, **params: Any) -> dict:
    """GET a JSON document from the Stats API, with caching and retries."""
    key = _cache_key(path, params)
    now = time.monotonic()

    with _cache_lock:
        hit = _cache.get(key)
        if hit is not None and now - hit[0] < CACHE_TTL_SECONDS:
            return hit[1]

    url = f"{API_BASE}/{path.lstrip('/')}"
    last_error: Exception | None = None
    for attempt in range(REQUEST_RETRIES):
        try:
            response = requests.get(
                url,
                params=params,
                timeout=REQUEST_TIMEOUT,
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:  # network error, bad status, bad JSON
            last_error = exc
            if attempt < REQUEST_RETRIES - 1:
                time.sleep(2**attempt)
            continue

        with _cache_lock:
            _cache[key] = (time.monotonic(), payload)
        return payload

    raise MlbApiError(f"MLB Stats API request failed: {url} ({last_error})")


def clear_cache() -> None:
    """Drop every cached response so the next call refetches."""
    with _cache_lock:
        _cache.clear()


# --------------------------------------------------------------------------
# Player and season lookup
# --------------------------------------------------------------------------


def resolve_player_id(name: str = PLAYER_NAME) -> int:
    """Look up a player's MLB id by name, falling back to the known constant."""
    try:
        payload = _get("people/search", names=name, sportIds=1)
    except MlbApiError:
        return PLAYER_ID_FALLBACK

    people = payload.get("people") or []
    for person in people:
        if person.get("fullName", "").casefold() == name.casefold():
            return int(person["id"])
    if people:
        return int(people[0]["id"])
    return PLAYER_ID_FALLBACK


def current_season(today: dt.date | None = None) -> int:
    """The season whose game log is most likely to be interesting today.

    Between January and February the previous season is still the last one
    played, so it is the one worth showing.
    """
    today = today or dt.date.today()
    return today.year - 1 if today.month <= 2 else today.year


# --------------------------------------------------------------------------
# Game log
# --------------------------------------------------------------------------


def _to_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _split_to_row(split: dict) -> dict:
    stat = split.get("stat") or {}
    hits = _to_int(stat.get("hits"))
    doubles = _to_int(stat.get("doubles"))
    triples = _to_int(stat.get("triples"))
    hr = _to_int(stat.get("homeRuns"))
    total_bases = stat.get("totalBases")
    tb = (
        _to_int(total_bases)
        if total_bases is not None
        else hits + doubles + 2 * triples + 3 * hr
    )
    return {
        "date": split.get("date"),
        "season": _to_int(split.get("season")),
        "game_pk": _to_int((split.get("game") or {}).get("gamePk")),
        "team": (split.get("team") or {}).get("abbreviation")
        or (split.get("team") or {}).get("name", ""),
        "opponent": (split.get("opponent") or {}).get("abbreviation")
        or (split.get("opponent") or {}).get("name", ""),
        "home_away": "Home" if split.get("isHome") else "Away",
        "pa": _to_int(stat.get("plateAppearances")),
        "ab": _to_int(stat.get("atBats")),
        "r": _to_int(stat.get("runs")),
        "h": hits,
        "doubles": doubles,
        "triples": triples,
        "hr": hr,
        "rbi": _to_int(stat.get("rbi")),
        "bb": _to_int(stat.get("baseOnBalls")),
        "hbp": _to_int(stat.get("hitByPitch")),
        "so": _to_int(stat.get("strikeOuts")),
        "sf": _to_int(stat.get("sacFlies")),
        "tb": tb,
    }


def parse_game_log(payload: dict) -> pd.DataFrame:
    """Turn a ``stats=gameLog`` payload into a tidy, date-sorted frame."""
    splits: list[dict] = []
    for block in payload.get("stats") or []:
        splits.extend(block.get("splits") or [])

    if not splits:
        return pd.DataFrame(columns=GAME_LOG_COLUMNS).astype({"date": "datetime64[ns]"})

    frame = pd.DataFrame([_split_to_row(split) for split in splits])
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame = frame.dropna(subset=["date"])
    frame = frame.sort_values(["date", "game_pk"], kind="stable").reset_index(drop=True)
    return frame[GAME_LOG_COLUMNS]


def fetch_game_log(
    player_id: int, season: int, game_type: str = "R"
) -> pd.DataFrame:
    """Fetch one season of hitting game logs, oldest game first."""
    payload = _get(
        f"people/{player_id}/stats",
        stats="gameLog",
        group="hitting",
        season=season,
        gameType=game_type,
    )
    return parse_game_log(payload)


def fetch_recent_games(
    player_id: int,
    min_games: int,
    season: int | None = None,
    game_type: str = "R",
    max_seasons_back: int = 3,
) -> pd.DataFrame:
    """Fetch at least ``min_games`` games, reaching into prior seasons if needed.

    Early in a season (or in the offseason) the current year may not hold ten
    games yet, so previous seasons are prepended until the requested count is
    met or ``max_seasons_back`` seasons have been tried.
    """
    season = season or current_season()
    frames: list[pd.DataFrame] = []
    total = 0

    for offset in range(max_seasons_back + 1):
        frame = fetch_game_log(player_id, season - offset, game_type=game_type)
        if not frame.empty:
            frames.append(frame)
            total += len(frame)
        if total >= min_games:
            break

    if not frames:
        return pd.DataFrame(columns=GAME_LOG_COLUMNS).astype({"date": "datetime64[ns]"})

    combined = pd.concat(reversed(frames), ignore_index=True)
    return combined.sort_values(["date", "game_pk"], kind="stable").reset_index(
        drop=True
    )


# --------------------------------------------------------------------------
# Derived numbers
# --------------------------------------------------------------------------


def last_n_games(game_log: pd.DataFrame, n: int) -> pd.DataFrame:
    """The most recent ``n`` games played, oldest first."""
    if game_log.empty:
        return game_log
    return game_log.tail(n).reset_index(drop=True)


def batting_average(hits: int, at_bats: int) -> float | None:
    """Hits over at-bats; ``None`` when there is no at-bat to divide by."""
    return hits / at_bats if at_bats else None


#: Counting stats totalled by :func:`summarize`.
COUNTING_STATS = ["pa", "ab", "r", "h", "hr", "rbi", "bb", "hbp", "so", "sf", "tb"]


def summarize(games: pd.DataFrame) -> dict[str, Any]:
    """Totals and slash-line rates for a set of games.

    The returned dict always carries the same keys, so callers can render an
    empty window without guarding every lookup.
    """
    if games.empty:
        return {
            "games": 0,
            "avg": None,
            "obp": None,
            "slg": None,
            "ops": None,
            "start_date": None,
            "end_date": None,
            **{column: 0 for column in COUNTING_STATS},
        }

    totals = {column: int(games[column].sum()) for column in COUNTING_STATS}
    avg = batting_average(totals["h"], totals["ab"])
    on_base_denominator = totals["ab"] + totals["bb"] + totals["hbp"] + totals["sf"]
    obp = (
        (totals["h"] + totals["bb"] + totals["hbp"]) / on_base_denominator
        if on_base_denominator
        else None
    )
    slg = totals["tb"] / totals["ab"] if totals["ab"] else None
    ops = obp + slg if obp is not None and slg is not None else None

    return {
        "games": int(len(games)),
        "avg": avg,
        "obp": obp,
        "slg": slg,
        "ops": ops,
        "start_date": games["date"].iloc[0].date(),
        "end_date": games["date"].iloc[-1].date(),
        **totals,
    }


def with_trend_columns(window: pd.DataFrame) -> pd.DataFrame:
    """Add per-game and cumulative batting averages to a window of games."""
    frame = window.copy()
    frame["game_avg"] = [
        batting_average(h, ab) for h, ab in zip(frame["h"], frame["ab"])
    ]
    cumulative_hits = frame["h"].cumsum()
    cumulative_ab = frame["ab"].cumsum()
    frame["cum_h"] = cumulative_hits
    frame["cum_ab"] = cumulative_ab
    frame["cum_avg"] = [
        batting_average(h, ab) for h, ab in zip(cumulative_hits, cumulative_ab)
    ]
    return frame


def rolling_average(game_log: pd.DataFrame, window: int, tail: int) -> pd.DataFrame:
    """Trailing ``window``-game batting average for the last ``tail`` games.

    Every returned point covers a full ``window`` games, using games from before
    the displayed range. Games without a complete window behind them are dropped
    rather than plotted as a partial average, which would read as a wild swing
    early in a season when it is really a one-game sample.
    """
    if game_log.empty:
        return game_log.assign(roll_avg=[], roll_h=[], roll_ab=[])

    frame = game_log.copy()
    rolling_hits = frame["h"].rolling(window=window, min_periods=window).sum()
    rolling_ab = frame["ab"].rolling(window=window, min_periods=window).sum()
    frame["roll_h"] = rolling_hits
    frame["roll_ab"] = rolling_ab
    frame = frame.dropna(subset=["roll_h", "roll_ab"]).copy()
    if frame.empty:
        return frame.assign(roll_avg=[])

    frame["roll_h"] = frame["roll_h"].astype(int)
    frame["roll_ab"] = frame["roll_ab"].astype(int)
    frame["roll_avg"] = [
        batting_average(h, ab) for h, ab in zip(frame["roll_h"], frame["roll_ab"])
    ]
    return frame.tail(tail).reset_index(drop=True)


def season_to_date(player_id: int, season: int, game_type: str = "R") -> dict[str, Any]:
    """Season totals, used as the baseline the recent window is read against."""
    payload = _get(
        f"people/{player_id}/stats",
        stats="season",
        group="hitting",
        season=season,
        gameType=game_type,
    )
    splits: list[dict] = []
    for block in payload.get("stats") or []:
        splits.extend(block.get("splits") or [])
    if not splits:
        return {"season": season, "avg": None, "ab": 0, "h": 0, "games": 0}

    stat = splits[0].get("stat") or {}
    at_bats = _to_int(stat.get("atBats"))
    hits = _to_int(stat.get("hits"))
    return {
        "season": season,
        "games": _to_int(stat.get("gamesPlayed")),
        "ab": at_bats,
        "h": hits,
        "hr": _to_int(stat.get("homeRuns")),
        "rbi": _to_int(stat.get("rbi")),
        "avg": batting_average(hits, at_bats),
    }


def format_avg(value: float | None) -> str:
    """Baseball's three-decimal, leading-zero-free average format.

    Rounds half away from zero (.3125 -> .313) rather than to even, matching
    how averages are published.
    """
    if value is None:
        return "—"
    quantized = Decimal(value).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    text = f"{quantized:.3f}"
    return text[1:] if text.startswith("0.") else text
