# Kyle Schwarber batting dashboard

A [Shiny for Python](https://shiny.posit.co/py/) dashboard for
[Posit Connect](https://posit.co/products/enterprise/connect/) that reports Kyle
Schwarber's batting average over his most recent games, defaulting to a ten-game
window. Data comes from the public MLB Stats API, live, every time the app loads.

![The dashboard, showing a ten-game batting average with a trend chart, a
per-game hits chart, and the underlying game log](docs/screenshot.png)

## What it shows

- **The headline number** — batting average across the window, as total hits
  divided by total at-bats. That is not the same as averaging the ten single-game
  averages, and the totals-based figure is the one that matches published splits.
- **How he got there** — a trend chart, in either of two readings:
  - *Cumulative through the window*: the average as it accrued from the first
    game of the window to the last, so the final point is the headline number.
  - *Trailing window average*: a rolling ten-game average plotted over the last
    ten games, so you can see whether the ten-game number is climbing or sliding.
    Only points with a full window behind them are plotted.
- **Per-game context** — hits per game against at-bats, so a `0-for-5` reads
  differently from a `0-for-2`.
- **The game log** — the underlying rows, so every number on the page can be
  checked by hand.

The season-to-date average is drawn as a dashed baseline on the trend chart and
quoted under the headline, which is what makes the window mean anything: `.324`
is only interesting next to what he has done all year.

Controls in the sidebar change the window size (5 / 10 / 15 / 25 games), the
season, regular season vs. postseason, and light/dark appearance.

## Deploying to Posit Connect

The repository is a self-contained Connect bundle: `manifest.json` declares the
Shiny entrypoint (`app:app`), and `requirements.txt` pins the runtime.

**With the rsconnect CLI:**

```bash
pip install rsconnect-python

rsconnect add --server https://connect.example.com --name prod --api-key "$CONNECT_API_KEY"
rsconnect deploy shiny . --name prod --entrypoint app:app --title "Kyle Schwarber — batting average"
```

**Git-backed deployment:** in Connect, choose *Publish → Import from Git*, point
it at this repository and branch, and select `manifest.json` at the repository
root. Connect will redeploy on each push.

After changing dependencies, regenerate the manifest so the checksums match:

```bash
rsconnect write-manifest shiny . --entrypoint app:app --overwrite
```

### Network access

The Connect server needs outbound HTTPS to `statsapi.mlb.com`. No API key or
account is required — the endpoint is public — but egress is the one thing that
has to be allowed. If it is blocked, the dashboard says so at the top of the
page and reports the underlying connection error rather than failing silently.

Responses are cached in-process for 15 minutes (`CACHE_TTL_SECONDS` in
`mlb_data.py`); **Refresh data** clears the cache and refetches. On Connect,
consider enabling *Run off a scheduled process* or raising the minimum number of
processes if you want the first visitor of the day to skip the cold fetch.

## Running locally

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt

shiny run app.py --reload
```

Without network access to the MLB API, point the app at a recorded game log:

```bash
SCHWARBER_FIXTURE=tests/fixtures/gamelog_2026.json shiny run app.py
```

The sidebar then reads *Fixture file (offline mode)* so nobody mistakes the
synthetic numbers for real ones.

## Tests

```bash
pytest
```

The tests run entirely offline against `tests/fixtures/gamelog_2026.json`, and
cover the parts worth pinning down: the window is the last *n* games played, the
average is totals-based, a trailing average never plots a partial window, and
the summary keeps a stable shape when there are no games at all. Regenerate the
fixture with `python tests/make_fixture.py`.

## Layout

| File | Purpose |
| --- | --- |
| `app.py` | Shiny UI, reactive wiring, and the two Plotly figures |
| `mlb_data.py` | MLB Stats API client, caching, and the batting-average math |
| `theme.py` | Chart palette and shared Plotly layout, for light and dark |
| `manifest.json` | Posit Connect bundle manifest |
| `requirements.txt` | Pinned runtime dependencies |
| `tests/` | Offline tests and the recorded fixture |

## A note on the data

`gameType=R` counts regular-season games only; switch the sidebar to
*Postseason* for October. "Last ten games" means the last ten games he appeared
in — a game he entered without batting counts toward the ten and, having no
at-bats, leaves the average unchanged. Early in a season the app reaches back
into the previous season to fill the window, and says so in a banner when fewer
games than requested are available.
