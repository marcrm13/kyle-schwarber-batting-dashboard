"""Chart palette and Plotly styling for the dashboard.

Colors come from the validated default data-viz palette: a single blue hue
(sequential) for the marks, neutral ink for text, and a recessive gray for
grid lines and baselines. Both modes are selected explicitly rather than
flipped, so the dark steps are chosen for the dark surface.
"""

from __future__ import annotations

from typing import Any

LIGHT = {
    "surface": "#fcfcfb",
    "text_primary": "#0b0b0b",
    "text_secondary": "#52514e",
    "text_muted": "#7a7972",
    "grid": "#e6e5e1",
    "axis": "#c9c8c2",
    # Single-hue sequential blue: solid step for the value, light step for the
    # "capacity" track behind it.
    "accent": "#2a78d6",
    "accent_strong": "#184f95",
    "track": "#86b6ef",
    "baseline": "#a3a29b",
}

DARK = {
    "surface": "#1a1a19",
    "text_primary": "#ffffff",
    "text_secondary": "#c3c2b7",
    "text_muted": "#96958c",
    "grid": "#2f2f2d",
    "axis": "#45443f",
    "accent": "#3987e5",
    "accent_strong": "#86b6ef",
    "track": "#184f95",
    "baseline": "#6f6e68",
}

FONT_FAMILY = (
    'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif'
)

#: Chrome-free Plotly config; the charts are read, not authored.
PLOTLY_CONFIG: dict[str, Any] = {
    "displayModeBar": False,
    "responsive": True,
    "scrollZoom": False,
}


def palette(mode: str) -> dict[str, str]:
    """The color role table for ``"light"`` or ``"dark"``."""
    return DARK if mode == "dark" else LIGHT


def base_layout(mode: str) -> dict[str, Any]:
    """Layout defaults shared by every figure in the dashboard."""
    colors = palette(mode)
    return {
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "rgba(0,0,0,0)",
        "font": {
            "family": FONT_FAMILY,
            "size": 13,
            "color": colors["text_secondary"],
        },
        "margin": {"l": 56, "r": 24, "t": 16, "b": 48},
        "hoverlabel": {
            "bgcolor": colors["surface"],
            "bordercolor": colors["axis"],
            "font": {
                "family": FONT_FAMILY,
                "size": 13,
                "color": colors["text_primary"],
            },
        },
        "xaxis": {
            "showgrid": False,
            "zeroline": False,
            "linecolor": colors["axis"],
            "ticks": "outside",
            "tickcolor": colors["axis"],
            "ticklen": 4,
            "tickfont": {"color": colors["text_secondary"]},
        },
        "yaxis": {
            "showgrid": True,
            "gridcolor": colors["grid"],
            "gridwidth": 1,
            "zeroline": False,
            "showline": False,
            "ticks": "",
            "tickfont": {"color": colors["text_secondary"]},
        },
    }
