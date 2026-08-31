"""Regenerate the offline game-log fixture used by the tests.

The shape mirrors a real ``stats=gameLog&group=hitting`` response from
statsapi.mlb.com; the numbers are synthetic and deterministic.
"""

import datetime as dt
import json
import pathlib
import random

OPPONENTS = ["NYM", "ATL", "WSH", "MIA", "SDP", "LAD", "CHC", "STL", "MIL", "CIN"]


def build(n_games: int = 25, seed: int = 11) -> dict:
    rng = random.Random(seed)
    start = dt.date(2026, 8, 1)
    splits = []
    for i in range(n_games):
        at_bats = rng.choice([3, 4, 4, 4, 5])
        hits = min(at_bats, rng.choice([0, 0, 1, 1, 1, 2, 2, 3]))
        home_runs = 1 if hits and rng.random() < 0.28 else 0
        doubles = 1 if hits - home_runs > 0 and rng.random() < 0.25 else 0
        walks = rng.choice([0, 1, 1, 2])
        singles = max(0, hits - home_runs - doubles)
        total_bases = singles + 2 * doubles + 4 * home_runs
        splits.append(
            {
                "season": "2026",
                "date": (start + dt.timedelta(days=i)).isoformat(),
                "gameType": "R",
                "isHome": i % 2 == 0,
                "isWin": rng.random() < 0.5,
                "game": {"gamePk": 800000 + i},
                "team": {"id": 143, "name": "Philadelphia Phillies", "abbreviation": "PHI"},
                "opponent": {"id": 100 + i, "name": "Opponent", "abbreviation": OPPONENTS[i % len(OPPONENTS)]},
                "stat": {
                    "gamesPlayed": 1,
                    "plateAppearances": at_bats + walks,
                    "atBats": at_bats,
                    "runs": home_runs + (1 if rng.random() < 0.2 else 0),
                    "hits": hits,
                    "doubles": doubles,
                    "triples": 0,
                    "homeRuns": home_runs,
                    "rbi": home_runs + rng.choice([0, 0, 1]),
                    "baseOnBalls": walks,
                    "intentionalWalks": 0,
                    "hitByPitch": 0,
                    "strikeOuts": rng.choice([0, 1, 1, 2, 3]),
                    "sacFlies": 0,
                    "sacBunts": 0,
                    "totalBases": total_bases,
                    "avg": f"{hits / at_bats:.3f}".lstrip("0"),
                },
            }
        )

    return {
        "stats": [
            {
                "type": {"displayName": "gameLog"},
                "group": {"displayName": "hitting"},
                "splits": splits,
            }
        ]
    }


if __name__ == "__main__":
    target = pathlib.Path(__file__).parent / "fixtures" / "gamelog_2026.json"
    target.write_text(json.dumps(build(), indent=2) + "\n")
    print(f"wrote {target}")
