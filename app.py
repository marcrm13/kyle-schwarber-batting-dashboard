"""Kyle Schwarber — recent batting average dashboard.

A Shiny for Python app for Posit Connect. It pulls Schwarber's game-by-game
hitting log from the public MLB Stats API and reports his batting average over
the most recent games, defaulting to a ten-game window.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
from typing import Any

import pandas as pd
import plotly.graph_objects as go
from shiny import App, reactive, render, ui
from shinywidgets import output_widget, render_widget

import mlb_data
import theme

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

#: Point this at a saved gameLog JSON document to run without network access
#: (handy for local development and for the screenshots in the README).
FIXTURE_PATH = os.environ.get("SCHWARBER_FIXTURE")

WINDOW_CHOICES = {
    "5": "Last 5 games",
    "10": "Last 10 games",
    "15": "Last 15 games",
    "25": "Last 25 games",
}

GAME_TYPE_CHOICES = {"R": "Regular season", "P": "Postseason"}

SEASON_CHOICES = [
    str(year)
    for year in range(mlb_data.current_season(), mlb_data.current_season() - 4, -1)
]

CSS = """
.hero-value-box .value-box-value { font-size: 3.25rem; line-height: 1.05; font-weight: 600;
  font-variant-numeric: tabular-nums; }
.value-box-value { font-variant-numeric: tabular-nums; font-size: 1.6rem;
  white-space: nowrap; }
.stat-caption { font-size: .8125rem; opacity: .75; }
.sidebar-note { font-size: .8125rem; opacity: .75; line-height: 1.45; }
"""

# --------------------------------------------------------------------------
# UI
# --------------------------------------------------------------------------

app_ui = ui.page_sidebar(
    ui.sidebar(
        ui.input_select("window", "Game window", WINDOW_CHOICES, selected="10"),
        ui.input_select("season", "Season", SEASON_CHOICES, selected=SEASON_CHOICES[0]),
        ui.input_select(
            "game_type", "Game type", GAME_TYPE_CHOICES, selected="R"
        ),
        ui.input_radio_buttons(
            "trend_mode",
            "Trend line",
            {
                "cumulative": "Cumulative through the window",
                "rolling": "Trailing window average",
            },
            selected="cumulative",
        ),
        ui.input_action_button("refresh", "Refresh data", class_="btn-sm"),
        ui.input_dark_mode(id="color_mode"),
        ui.hr(),
        ui.output_ui("sidebar_note"),
        width=290,
        open="desktop",
    ),
    ui.output_ui("status_banner"),
    ui.layout_columns(
        ui.value_box(
            ui.output_text("avg_label"),
            ui.output_text("avg_value"),
            ui.output_text("avg_caption"),
            class_="hero-value-box",
        ),
        ui.value_box(
            "H / AB",
            ui.output_text("hits_value"),
            ui.output_text("hits_caption"),
        ),
        ui.value_box(
            "OBP / SLG",
            ui.output_text("slash_value"),
            ui.output_text("slash_caption"),
        ),
        ui.value_box(
            "HR / RBI",
            ui.output_text("power_value"),
            ui.output_text("power_caption"),
        ),
        ui.value_box(
            "BB / K",
            ui.output_text("discipline_value"),
            ui.output_text("discipline_caption"),
        ),
        col_widths={"sm": 12, "md": 6, "xl": [3, 2, 3, 2, 2]},
        fill=False,
    ),
    ui.layout_columns(
        ui.card(
            ui.card_header(ui.output_text("trend_title")),
            output_widget("trend_chart", height="340px"),
            full_screen=True,
        ),
        ui.card(
            ui.card_header("Hits per game, against at-bats"),
            output_widget("per_game_chart", height="340px"),
            full_screen=True,
        ),
        col_widths={"sm": 12, "xl": [7, 5]},
    ),
    ui.card(
        ui.card_header("Game log"),
        ui.output_data_frame("game_table"),
        full_screen=True,
    ),
    ui.head_content(ui.tags.style(CSS)),
    title="Kyle Schwarber — recent batting average",
    fillable=False,
    window_title="Schwarber batting dashboard",
)


# --------------------------------------------------------------------------
# Server
# --------------------------------------------------------------------------


def server(input, output, session):  # noqa: A002 - Shiny's signature
    @reactive.calc
    def window_size() -> int:
        return int(input.window())

    @reactive.calc
    def selected_season() -> int:
        return int(input.season())

    @reactive.calc
    def data_bundle() -> dict[str, Any]:
        """Game log, season baseline, and any error worth telling the user."""
        input.refresh()  # re-run when the refresh button is pressed

        if FIXTURE_PATH:
            payload = json.loads(pathlib.Path(FIXTURE_PATH).read_text())
            log = mlb_data.parse_game_log(payload)
            season_stats = {
                "season": selected_season(),
                "games": len(log),
                "ab": int(log["ab"].sum()),
                "h": int(log["h"].sum()),
                "avg": mlb_data.batting_average(
                    int(log["h"].sum()), int(log["ab"].sum())
                ),
            }
            return {
                "log": log,
                "season_stats": season_stats,
                "error": None,
                "source": "fixture",
            }

        try:
            player_id = mlb_data.resolve_player_id()
            log = mlb_data.fetch_recent_games(
                player_id,
                min_games=window_size() * 2,
                season=selected_season(),
                game_type=input.game_type(),
            )
            season_stats = mlb_data.season_to_date(
                player_id, selected_season(), game_type=input.game_type()
            )
        except mlb_data.MlbApiError as exc:
            return {
                "log": pd.DataFrame(columns=mlb_data.GAME_LOG_COLUMNS),
                "season_stats": {"season": selected_season(), "avg": None},
                "error": str(exc),
                "source": "live",
            }

        return {
            "log": log,
            "season_stats": season_stats,
            "error": None,
            "source": "live",
        }

    @reactive.effect
    @reactive.event(input.refresh)
    def _drop_cache():
        mlb_data.clear_cache()

    @reactive.calc
    def window_games() -> pd.DataFrame:
        return mlb_data.last_n_games(data_bundle()["log"], window_size())

    @reactive.calc
    def window_summary() -> dict[str, Any]:
        return mlb_data.summarize(window_games())

    @reactive.calc
    def trend_frame() -> pd.DataFrame:
        if input.trend_mode() == "rolling":
            frame = mlb_data.rolling_average(
                data_bundle()["log"], window=window_size(), tail=window_size()
            )
            if frame.empty:
                return frame
            return frame.assign(
                plot_avg=frame["roll_avg"],
                plot_h=frame["roll_h"],
                plot_ab=frame["roll_ab"],
            )
        frame = mlb_data.with_trend_columns(window_games())
        if frame.empty:
            return frame
        return frame.assign(
            plot_avg=frame["cum_avg"], plot_h=frame["cum_h"], plot_ab=frame["cum_ab"]
        )

    @reactive.calc
    def mode() -> str:
        return "dark" if input.color_mode() == "dark" else "light"

    # ---------------------------------------------------------------- text

    @render.text
    def avg_label():
        return f"Batting average, last {window_summary()['games'] or window_size()} games"

    @render.text
    def avg_value():
        return mlb_data.format_avg(window_summary()["avg"])

    @render.text
    def avg_caption():
        summary = window_summary()
        if not summary["games"]:
            return "No games in range"
        season_avg = data_bundle()["season_stats"].get("avg")
        span = f"{summary['start_date']:%b %-d} – {summary['end_date']:%b %-d}"
        if season_avg is None or summary["avg"] is None:
            return span
        delta = summary["avg"] - season_avg
        direction = "above" if delta >= 0 else "below"
        return (
            f"{span} · {mlb_data.format_avg(abs(delta))} {direction} his "
            f"{data_bundle()['season_stats']['season']} average of "
            f"{mlb_data.format_avg(season_avg)}"
        )

    @render.text
    def hits_value():
        summary = window_summary()
        return f"{summary['h']} / {summary['ab']}"

    @render.text
    def hits_caption():
        summary = window_summary()
        return f"Hits per at-bat over {summary['pa']} plate appearances"

    @render.text
    def slash_value():
        summary = window_summary()
        return (
            f"{mlb_data.format_avg(summary['obp'])} / "
            f"{mlb_data.format_avg(summary['slg'])}"
        )

    @render.text
    def slash_caption():
        return f"On-base / slugging · OPS {mlb_data.format_avg(window_summary()['ops'])}"

    @render.text
    def power_value():
        summary = window_summary()
        return f"{summary['hr']} / {summary['rbi']}"

    @render.text
    def power_caption():
        return f"Home runs / RBI · {window_summary()['tb']} total bases"

    @render.text
    def discipline_value():
        summary = window_summary()
        return f"{summary['bb']} / {summary['so']}"

    @render.text
    def discipline_caption():
        summary = window_summary()
        if not summary["pa"]:
            return "—"
        return f"Walks / strikeouts · {summary['so'] / summary['pa']:.0%} K rate"

    @render.text
    def trend_title():
        if input.trend_mode() == "rolling":
            return f"Trailing {window_size()}-game batting average"
        return f"Batting average across the last {window_size()} games"

    @render.ui
    def sidebar_note():
        bundle = data_bundle()
        source = (
            "Fixture file (offline mode)"
            if bundle["source"] == "fixture"
            else "MLB Stats API · statsapi.mlb.com"
        )
        return ui.div(
            ui.tags.strong("Source"),
            ui.br(),
            source,
            ui.br(),
            ui.br(),
            ui.tags.strong("Loaded"),
            ui.br(),
            dt.datetime.now().strftime("%b %d, %Y %H:%M"),
            ui.br(),
            ui.br(),
            "Batting average is total hits divided by total at-bats across the "
            "window, not the mean of the single-game averages.",
            class_="sidebar-note",
        )

    @render.ui
    def status_banner():
        bundle = data_bundle()
        if bundle["error"]:
            detail = bundle["error"]
            if len(detail) > 400:
                detail = detail[:400] + "…"
            return ui.div(
                ui.tags.strong("Could not reach the MLB Stats API."),
                " The dashboard needs outbound HTTPS to statsapi.mlb.com; "
                "check the server's network policy, then use Refresh data.",
                ui.tags.div(detail, class_="stat-caption mt-2"),
                class_="alert alert-danger",
                role="alert",
            )
        summary = window_summary()
        if summary["games"] == 0:
            return ui.div(
                "No games found for this season and game type yet.",
                class_="alert alert-warning",
                role="alert",
            )
        if summary["games"] < window_size():
            return ui.div(
                f"Only {summary['games']} games available; showing all of them.",
                class_="alert alert-warning",
                role="alert",
            )
        return None

    # -------------------------------------------------------------- charts

    def game_labels(frame: pd.DataFrame, style: str = "long") -> list[str]:
        fmt = "%b %-d" if style == "long" else "%-m/%-d"
        return [d.strftime(fmt) for d in frame["date"]]

    def thinned_ticks(labels: list[str], max_labels: int = 9) -> dict[str, Any]:
        """Label at most ``max_labels`` categories so dates never collide."""
        if len(labels) <= max_labels:
            return {"tickmode": "array", "tickvals": labels, "ticktext": labels}
        stride = -(-len(labels) // max_labels)  # ceiling division
        keep = list(range(len(labels) - 1, -1, -stride))[::-1]
        return {
            "tickmode": "array",
            "tickvals": [labels[i] for i in keep],
            "ticktext": [labels[i] for i in keep],
        }

    def avg_axis(values: list[float]) -> dict[str, Any]:
        """A batting-average y-axis: padded range, `.300`-style tick labels."""
        clean = [v for v in values if v is not None and not pd.isna(v)]
        if not clean:
            low, high = 0.0, 0.5
        else:
            low, high = min(clean), max(clean)
        pad = max((high - low) * 0.25, 0.03)
        low = max(0.0, low - pad)
        high = min(1.0, high + pad)
        span = high - low
        step = next(
            (candidate for candidate in (0.01, 0.025, 0.05, 0.1, 0.2) if span / candidate <= 7),
            0.25,
        )
        start = (int(low / step)) * step
        ticks = []
        value = start
        while value <= high + 1e-9:
            if value >= low - 1e-9:
                ticks.append(round(value, 4))
            value += step
        return {
            "range": [low, high],
            "tickvals": ticks,
            "ticktext": [mlb_data.format_avg(t) for t in ticks],
        }

    @render_widget
    def trend_chart():
        colors = theme.palette(mode())
        frame = trend_frame()
        figure = go.Figure()
        layout = theme.base_layout(mode())

        if frame.empty:
            message = (
                f"Not enough history yet for a trailing {window_size()}-game average"
                if input.trend_mode() == "rolling"
                else "No games to plot"
            )
            figure.update_layout(**layout)
            figure.add_annotation(
                text=message,
                showarrow=False,
                font={"color": colors["text_muted"], "size": 14},
            )
            figure.update_xaxes(visible=False)
            figure.update_yaxes(visible=False)
            return figure

        labels = game_labels(frame)
        season_avg = data_bundle()["season_stats"].get("avg")

        figure.add_trace(
            go.Scatter(
                x=labels,
                y=frame["plot_avg"],
                mode="lines+markers",
                name="Batting average",
                line={"color": colors["accent"], "width": 2, "shape": "linear"},
                marker={
                    "size": 9,
                    "color": colors["accent"],
                    "line": {"color": colors["surface"], "width": 2},
                },
                customdata=list(
                    zip(
                        frame["opponent"],
                        frame["home_away"],
                        frame["plot_h"],
                        frame["plot_ab"],
                        frame["h"],
                        frame["ab"],
                    )
                ),
                hovertemplate=(
                    "<b>%{x}</b> %{customdata[1]} %{customdata[0]}<br>"
                    "That game: %{customdata[4]}-for-%{customdata[5]}<br>"
                    "Running: %{customdata[2]}-for-%{customdata[3]} "
                    "(%{y:.3f})<extra></extra>"
                ),
            )
        )

        y_axis = avg_axis(list(frame["plot_avg"]) + ([season_avg] if season_avg else []))
        layout["yaxis"] = {**layout["yaxis"], **y_axis, "title": {"text": ""}}
        layout["xaxis"] = {
            **layout["xaxis"],
            **thinned_ticks(labels),
            "showspikes": True,
            "spikemode": "across",
            "spikethickness": 1,
            "spikedash": "dot",
            "spikecolor": colors["axis"],
        }
        layout["hovermode"] = "x unified"
        layout["showlegend"] = False
        figure.update_layout(**layout)

        if season_avg is not None:
            figure.add_hline(
                y=season_avg,
                line={"color": colors["baseline"], "width": 1.5, "dash": "dash"},
                annotation_text=(
                    f"{data_bundle()['season_stats']['season']} season "
                    f"{mlb_data.format_avg(season_avg)}"
                ),
                annotation_position="top left",
                annotation_font={"color": colors["text_muted"], "size": 12},
            )

        # Direct-label the endpoint rather than every point.
        last_value = frame["plot_avg"].iloc[-1]
        if last_value is not None and not pd.isna(last_value):
            figure.add_annotation(
                x=labels[-1],
                y=last_value,
                text=f"<b>{mlb_data.format_avg(last_value)}</b>",
                showarrow=False,
                xanchor="right",
                yanchor="bottom",
                yshift=12,
                font={"color": colors["text_primary"], "size": 14},
            )

        return figure

    @render_widget
    def per_game_chart():
        colors = theme.palette(mode())
        frame = window_games()
        layout = theme.base_layout(mode())
        figure = go.Figure()

        if frame.empty:
            figure.update_layout(**layout)
            figure.add_annotation(
                text="No games to plot",
                showarrow=False,
                font={"color": colors["text_muted"], "size": 14},
            )
            figure.update_xaxes(visible=False)
            figure.update_yaxes(visible=False)
            return figure

        labels = game_labels(frame, style="short")
        game_avgs = [mlb_data.batting_average(h, ab) for h, ab in zip(frame["h"], frame["ab"])]

        figure.add_trace(
            go.Bar(
                x=labels,
                y=frame["ab"],
                name="At-bats",
                marker={"color": colors["track"], "cornerradius": 4},
                width=0.62,
                # Direct labels only while they still fit; past that they are noise.
                text=(
                    [f"{h}/{ab}" for h, ab in zip(frame["h"], frame["ab"])]
                    if len(frame) <= 12
                    else None
                ),
                textposition="outside",
                textfont={"color": colors["text_secondary"], "size": 12},
                hoverinfo="skip",
            )
        )
        figure.add_trace(
            go.Bar(
                x=labels,
                y=frame["h"],
                name="Hits",
                marker={
                    "color": colors["accent"],
                    "cornerradius": 4,
                    "line": {"color": colors["surface"], "width": 2},
                },
                width=0.62,
                customdata=list(
                    zip(
                        frame["opponent"],
                        frame["home_away"],
                        frame["ab"],
                        [mlb_data.format_avg(a) for a in game_avgs],
                        frame["hr"],
                        frame["rbi"],
                        frame["bb"],
                        frame["so"],
                    )
                ),
                hovertemplate=(
                    "<b>%{x}</b> %{customdata[1]} %{customdata[0]}<br>"
                    "%{y}-for-%{customdata[2]} (%{customdata[3]})<br>"
                    "%{customdata[4]} HR · %{customdata[5]} RBI · "
                    "%{customdata[6]} BB · %{customdata[7]} K<extra></extra>"
                ),
            )
        )

        layout["barmode"] = "overlay"
        layout["bargap"] = 0.38
        layout["yaxis"] = {
            **layout["yaxis"],
            "dtick": 1,
            "range": [0, int(frame["ab"].max()) + 1],
            "title": {"text": ""},
        }
        layout["xaxis"] = {
            **layout["xaxis"],
            **thinned_ticks(labels, max_labels=8),
            "tickangle": 0,
            "automargin": True,
        }
        layout["legend"] = {
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "xanchor": "left",
            "x": 0,
            "font": {"color": colors["text_secondary"]},
        }
        layout["margin"] = {**layout["margin"], "t": 34}
        figure.update_layout(**layout)
        return figure

    # --------------------------------------------------------------- table

    @render.data_frame
    def game_table():
        frame = window_games()
        if frame.empty:
            return render.DataGrid(pd.DataFrame({"Game": []}))

        table = pd.DataFrame(
            {
                "Date": [d.strftime("%Y-%m-%d") for d in frame["date"]],
                "Opponent": [
                    f"{'vs' if ha == 'Home' else '@'} {opp}"
                    for ha, opp in zip(frame["home_away"], frame["opponent"])
                ],
                "AB": frame["ab"],
                "H": frame["h"],
                "2B": frame["doubles"],
                "3B": frame["triples"],
                "HR": frame["hr"],
                "RBI": frame["rbi"],
                "BB": frame["bb"],
                "K": frame["so"],
                "AVG": [
                    mlb_data.format_avg(mlb_data.batting_average(h, ab))
                    for h, ab in zip(frame["h"], frame["ab"])
                ],
            }
        ).iloc[::-1]

        return render.DataGrid(table, height="320px", summary=False)


app = App(app_ui, server)
