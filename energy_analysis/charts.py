"""Graphiques Plotly cohérents avec l'interface sombre Soleol."""

from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.graph_objects as go

from .config import (
    BRAND_ORANGE,
    EXPORT_COLOR,
    GRID_COLOR,
    IMPORT_COLOR,
    MUTED_TEXT_COLOR,
    PAPER_COLOR,
    PLOT_COLOR,
    TEXT_COLOR,
)
from .formatting import time_label

YEAR_COLORS = ("#E0553A", "#F4A261", "#B892FF", "#67C5B7", "#8AC926")


def _layout(title: str, height: int = 420, **extra: Any) -> dict[str, Any]:
    return {
        "title": {"text": title, "font": {"size": 18, "color": TEXT_COLOR}},
        "height": height,
        "paper_bgcolor": PAPER_COLOR,
        "plot_bgcolor": PLOT_COLOR,
        "font": {"color": TEXT_COLOR},
        "margin": {"l": 22, "r": 22, "t": 62, "b": 32},
        "legend": {
            "title": {"text": ""},
            "orientation": "h",
            "y": 1.10,
            "x": 0,
        },
        "hoverlabel": {"bgcolor": "#272B30", "font": {"color": TEXT_COLOR}},
        **extra,
    }


def _axes() -> dict[str, Any]:
    return {
        "showgrid": True,
        "gridcolor": GRID_COLOR,
        "zerolinecolor": GRID_COLOR,
        "tickfont": {"color": MUTED_TEXT_COLOR},
        "title_font": {"color": MUTED_TEXT_COLOR},
    }


def annual_energy_chart(summary: pd.DataFrame) -> go.Figure:
    figure = go.Figure()
    figure.add_bar(
        x=summary["year"],
        y=summary["import_kwh"],
        name="Import réseau",
        marker_color=IMPORT_COLOR,
        hovertemplate="%{x}<br>Import : %{y:,.0f} kWh<extra></extra>",
    )
    figure.add_bar(
        x=summary["year"],
        y=summary["export_kwh"],
        name="Export / injection",
        marker_color=EXPORT_COLOR,
        hovertemplate="%{x}<br>Injection : %{y:,.0f} kWh<extra></extra>",
    )
    figure.update_layout(**_layout("Import et injection par année", barmode="group"))
    figure.update_xaxes(**_axes(), title_text="")
    figure.update_yaxes(**_axes(), title_text="Énergie [kWh]")
    return figure


def monthly_energy_chart(summary: pd.DataFrame) -> go.Figure:
    figure = go.Figure()
    figure.add_bar(
        x=summary["label"],
        y=summary["import_kwh"],
        name="Import réseau",
        marker_color=IMPORT_COLOR,
        hovertemplate="%{x}<br>Import : %{y:,.0f} kWh<extra></extra>",
    )
    figure.add_bar(
        x=summary["label"],
        y=summary["export_kwh"],
        name="Export / injection",
        marker_color=EXPORT_COLOR,
        hovertemplate="%{x}<br>Injection : %{y:,.0f} kWh<extra></extra>",
    )
    figure.update_layout(**_layout("Import et injection par mois", height=460, barmode="group"))
    figure.update_xaxes(**_axes(), title_text="", tickangle=-40)
    figure.update_yaxes(**_axes(), title_text="Énergie [kWh]")
    return figure


def comparable_energy_chart(summary: pd.DataFrame) -> go.Figure:
    figure = go.Figure()
    figure.add_bar(
        x=summary["year"],
        y=summary["import_kwh"],
        name="Import réseau",
        marker_color=IMPORT_COLOR,
    )
    figure.add_bar(
        x=summary["year"],
        y=summary["export_kwh"],
        name="Export / injection",
        marker_color=EXPORT_COLOR,
    )
    figure.update_layout(
        **_layout("Comparaison sur les mêmes quarts d’heure", height=360, barmode="group")
    )
    figure.update_xaxes(**_axes(), title_text="")
    figure.update_yaxes(**_axes(), title_text="Énergie [kWh]")
    return figure


def typical_day_chart(
    profile: pd.DataFrame,
    season: str,
    solar_start_hour: int,
    solar_end_hour: int,
) -> go.Figure:
    """Affiche l'import au-dessus de zéro et l'injection au-dessous de zéro."""

    figure = go.Figure()
    if profile.empty:
        figure.update_layout(**_layout(f"Journée type — {season}", height=365))
        return figure
    values = list(profile["year"].drop_duplicates())
    for index, year in enumerate(values):
        subset = profile[profile["year"] == year]
        color = YEAR_COLORS[index % len(YEAR_COLORS)]
        label = str(year)
        figure.add_trace(
            go.Scatter(
                x=subset["minute_of_day"],
                y=subset["import_kw"],
                mode="lines",
                name=f"Import {label}",
                line={"color": color, "width": 2.6},
                hovertemplate=(
                    "%{customdata}<br>Import " + label + " : %{y:.2f} kW<extra></extra>"
                ),
                customdata=[time_label(value) for value in subset["minute_of_day"]],
            )
        )
        figure.add_trace(
            go.Scatter(
                x=subset["minute_of_day"],
                y=-subset["export_kw"],
                mode="lines",
                name=f"Injection {label}",
                line={"color": color, "width": 2.2, "dash": "dot"},
                hovertemplate=(
                    "%{customdata[0]}<br>Injection "
                    + label
                    + " : %{customdata[1]:.2f} kW<extra></extra>"
                ),
                customdata=[
                    [time_label(value), export]
                    for value, export in zip(
                        subset["minute_of_day"], subset["export_kw"], strict=True
                    )
                ],
            )
        )
    figure.add_vrect(
        x0=solar_start_hour * 60,
        x1=solar_end_hour * 60,
        fillcolor=BRAND_ORANGE,
        opacity=0.08,
        line_width=0,
        annotation_text="Fenêtre solaire",
        annotation_position="top left",
        annotation_font_color=MUTED_TEXT_COLOR,
    )
    figure.add_hline(y=0, line_color=GRID_COLOR, line_width=1.5)
    ticks = list(range(0, 24 * 60 + 1, 3 * 60))
    figure.update_layout(
        **_layout(f"Journée type — {season}", height=390, hovermode="x unified")
    )
    figure.update_xaxes(
        **_axes(),
        title_text="Heure",
        tickvals=ticks,
        ticktext=[time_label(value) for value in ticks],
        range=[0, 24 * 60],
    )
    figure.update_yaxes(
        **_axes(),
        title_text="Puissance moyenne [kW]",
        zeroline=True,
    )
    return figure


def threshold_hours_chart(hours_by_threshold: dict[int, float]) -> go.Figure:
    labels = [f">{threshold} kW" for threshold in hours_by_threshold]
    values = list(hours_by_threshold.values())
    figure = go.Figure(
        go.Bar(
            x=labels,
            y=values,
            marker_color=[BRAND_ORANGE, "#E76F51", "#F4A261", "#FFD166"],
            hovertemplate="%{x}<br>%{y:.0f} h<extra></extra>",
        )
    )
    figure.update_layout(**_layout("Disponibilité du surplus", height=320))
    figure.update_xaxes(**_axes(), title_text="")
    figure.update_yaxes(**_axes(), title_text="Durée [h]")
    return figure


def seasonal_energy_chart(metrics: dict[str, Any]) -> go.Figure:
    seasons = list(metrics["seasonal"])
    imports = [metrics["seasonal"][season]["import_kwh"] for season in seasons]
    exports = [metrics["seasonal"][season]["export_kwh"] for season in seasons]
    figure = go.Figure()
    figure.add_bar(x=seasons, y=imports, name="Import réseau", marker_color=IMPORT_COLOR)
    figure.add_bar(x=seasons, y=exports, name="Export / injection", marker_color=EXPORT_COLOR)
    figure.update_layout(
        **_layout("Lecture saisonnière des flux réseau", height=350, barmode="group")
    )
    figure.update_xaxes(**_axes(), title_text="")
    figure.update_yaxes(**_axes(), title_text="Énergie [kWh]")
    return figure
