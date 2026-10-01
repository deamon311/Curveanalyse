"""Rapport PDF client Soleol pour l'analyse de courbes de charge.

Le rapport est volontairement indépendant de Streamlit : il peut être testé
et généré à partir des tables déjà calculées par l'application.
"""

from __future__ import annotations

import os
from io import BytesIO
from typing import Any

# Streamlit Community Cloud and the test runner may not expose a writable home
# directory. Keep Matplotlib's cache in a known writable temporary location.
os.environ.setdefault("MPLCONFIGDIR", "/tmp/soleol-matplotlib")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from fpdf import FPDF

from .config import SEASON_ORDER

ORANGE = (224, 85, 58)
DARK = (18, 19, 21)
TEXT = (35, 35, 35)
MUTED = (100, 110, 120)
BLUE = (37, 99, 235)
GREEN = (34, 160, 85)
RED = (210, 55, 55)
LIGHT_BLUE = (239, 246, 255)
LIGHT_GREEN = (236, 253, 245)
LIGHT_RED = (254, 242, 242)
BORDER = (220, 225, 230)


def _tx(value: object) -> str:
    """Rend le texte compatible avec les polices de base PDF Latin-1."""

    replacements = {
        "—": "-",
        "–": "-",
        "→": "->",
        "≥": ">=",
        "≤": "<=",
        "≈": "~",
        "•": "-",
        "’": "'",
        "…": "...",
        "œ": "oe",
    }
    text = str(value)
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text.encode("latin-1", "replace").decode("latin-1")


def _fmt(value: float | int | None, decimals: int = 0) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value):,.{decimals}f}".replace(",", "'").replace(".", ",")


def _safe_sum(data: pd.DataFrame, column: str) -> float | None:
    if column not in data:
        return None
    value = data[column].sum(min_count=1)
    return float(value) if pd.notna(value) else None


class EnergyReportPDF(FPDF):
    """A4 portrait avec le langage visuel Soleol du rapport de référence."""

    def footer(self) -> None:
        self.set_y(-10)
        self.set_font("Helvetica", "", 7)
        self.set_text_color(*MUTED)
        self.cell(0, 5, "SOLEOL - Conseil énergétique", align="L")
        self.set_y(-10)
        self.cell(0, 5, _tx(f"Page {self.page_no()} / {{nb}}"), align="R")


def _sidebar(
    pdf: EnergyReportPDF,
    *,
    client_name: str,
    grd: str,
    offer: str,
    period: str,
) -> None:
    pdf.set_fill_color(*DARK)
    pdf.rect(0, 0, 52, 297, style="F")
    pdf.set_xy(8, 14)
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(36, 7, "SOLEOL", ln=True)
    pdf.set_x(8)
    pdf.set_font("Helvetica", "", 7.5)
    pdf.set_text_color(230, 235, 240)
    pdf.cell(36, 4.5, _tx("CONSEIL ÉNERGÉTIQUE"), ln=True)
    pdf.set_draw_color(*ORANGE)
    pdf.line(8, 32, 22, 32)
    pdf.set_xy(8, 39)
    pdf.set_font("Helvetica", "B", 7.5)
    pdf.set_text_color(*ORANGE)
    pdf.cell(36, 4, _tx("ANALYSE PHOTOVOLTAÏQUE"), ln=True)

    entries = (
        ("CLIENT", client_name or "À renseigner"),
        ("GRD", grd),
        ("TARIF", offer),
        ("PÉRIODE", period),
    )
    y = 55
    for label, value in entries:
        pdf.set_xy(8, y)
        pdf.set_font("Helvetica", "B", 6.5)
        pdf.set_text_color(*ORANGE)
        pdf.cell(36, 3.8, _tx(label), ln=True)
        pdf.set_x(8)
        pdf.set_font("Helvetica", "", 7.2)
        pdf.set_text_color(255, 255, 255)
        pdf.multi_cell(36, 3.8, _tx(value), align="L")
        y += 18 if len(str(value)) > 32 else 14

    pdf.set_xy(8, 224)
    pdf.set_font("Helvetica", "B", 8.5)
    pdf.set_text_color(*ORANGE)
    pdf.multi_cell(36, 4.2, _tx("Réduire les coûts,\nprioriser les bons usages."), align="L")


def _section_title(pdf: EnergyReportPDF, x: float, y: float, text: str) -> None:
    pdf.set_xy(x, y)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*ORANGE)
    pdf.cell(142, 6, _tx(text))


def _metric_box(
    pdf: EnergyReportPDF,
    x: float,
    y: float,
    w: float,
    h: float,
    label: str,
    value: str,
    subtitle: str,
    color: tuple[int, int, int] = BLUE,
) -> None:
    pdf.set_draw_color(*BORDER)
    pdf.set_fill_color(255, 255, 255)
    pdf.rect(x, y, w, h, style="DF")
    pdf.set_xy(x + 4, y + 4)
    pdf.set_font("Helvetica", "B", 6.8)
    pdf.set_text_color(*TEXT)
    pdf.multi_cell(w - 8, 3.4, _tx(label.upper()))
    pdf.set_xy(x + 4, y + 13)
    pdf.set_font("Helvetica", "B", 12.5 if len(value) < 18 else 9.5)
    pdf.set_text_color(*color)
    pdf.cell(w - 8, 6, _tx(value))
    pdf.set_xy(x + 4, y + h - 8)
    pdf.set_font("Helvetica", "", 6.2)
    pdf.set_text_color(*MUTED)
    pdf.multi_cell(w - 8, 3.1, _tx(subtitle))


def _info_box(
    pdf: EnergyReportPDF,
    x: float,
    y: float,
    w: float,
    h: float,
    title: str,
    text: str,
    fill: tuple[int, int, int],
    border: tuple[int, int, int],
) -> None:
    pdf.set_draw_color(*border)
    pdf.set_fill_color(*fill)
    pdf.rect(x, y, w, h, style="DF")
    pdf.set_xy(x + 5, y + 4)
    pdf.set_font("Helvetica", "B", 7.5)
    pdf.set_text_color(*border)
    pdf.cell(w - 10, 4, _tx(title.upper()))
    pdf.set_xy(x + 5, y + 10)
    pdf.set_font("Helvetica", "", 7.6)
    pdf.set_text_color(*TEXT)
    pdf.multi_cell(w - 10, 3.8, _tx(text), align="L")


def _monthly_chart(monthly: pd.DataFrame, export_available: bool) -> BytesIO:
    table = monthly.copy()
    table["label"] = table.get("label", pd.Series(dtype="object")).astype(str)
    imports = pd.to_numeric(table.get("import_kwh"), errors="coerce")
    exports = pd.to_numeric(table.get("export_kwh"), errors="coerce")
    x = np.arange(len(table))
    fig, ax = plt.subplots(figsize=(10.8, 3.25))
    ax.bar(x - 0.2, imports, width=0.38, label="Import réseau", color="#E0553A")
    if export_available and exports.notna().any():
        ax.bar(x + 0.2, exports, width=0.38, label="Injection PV", color="#2EA584")
    ax.set_xticks(x)
    ax.set_xticklabels(table["label"], rotation=42, ha="right", fontsize=7.2)
    ax.set_ylabel("kWh", fontsize=8)
    ax.set_title("Flux réseau par mois", fontsize=11, fontweight="bold", pad=8)
    ax.grid(axis="y", alpha=0.18)
    ax.legend(fontsize=8, frameon=False, loc="upper right")
    fig.tight_layout(pad=0.8)
    buffer = BytesIO()
    fig.savefig(buffer, format="png", dpi=165, bbox_inches="tight", pad_inches=0.03)
    plt.close(fig)
    buffer.seek(0)
    return buffer


def _seasonal_chart(data: pd.DataFrame, export_available: bool) -> BytesIO:
    fig, axes = plt.subplots(2, 2, figsize=(10.8, 5.0), sharex=True)
    for axis, season in zip(axes.flat, SEASON_ORDER):
        subset = data[data["season"] == season]
        grouped = subset.groupby("minute_of_day", as_index=False).agg(
            import_kw=("import_kw", "mean"), export_kw=("export_kw", "mean")
        )
        hours = grouped["minute_of_day"] / 60
        axis.plot(hours, grouped["import_kw"], color="#E0553A", lw=1.5, label="Import")
        if export_available and grouped["export_kw"].notna().any():
            axis.plot(hours, -grouped["export_kw"], color="#2EA584", lw=1.35, label="Injection")
        axis.axhline(0, color="#8A8A8A", lw=0.6)
        axis.set_title(season, fontsize=9, fontweight="bold")
        axis.grid(alpha=0.18)
        axis.set_xlim(0, 24)
        axis.set_xticks((0, 6, 12, 18, 24))
        axis.tick_params(labelsize=7)
    axes[0, 0].set_ylabel("kW")
    axes[1, 0].set_ylabel("kW")
    handles, labels = axes[0, 0].get_legend_handles_labels()
    # Reserve a dedicated band for the heading and legend. Otherwise the
    # legend overlaps the title after the figure is embedded in the PDF.
    fig.suptitle("Journées types saisonnières", fontsize=11, fontweight="bold", y=0.995)
    if handles:
        fig.legend(
            handles,
            labels,
            ncol=2,
            fontsize=7.2,
            frameon=False,
            loc="upper center",
            bbox_to_anchor=(0.5, 0.955),
        )
    fig.tight_layout(rect=(0, 0, 1, 0.87), pad=0.8)
    buffer = BytesIO()
    fig.savefig(buffer, format="png", dpi=165, bbox_inches="tight", pad_inches=0.03)
    plt.close(fig)
    buffer.seek(0)
    return buffer


def _billing_chart(annual_billing: pd.DataFrame) -> BytesIO | None:
    values = {
        "Énergie": _safe_sum(annual_billing, "energy_cost_chf"),
        "Distribution": _safe_sum(annual_billing, "distribution_cost_chf"),
        "Swissgrid": _safe_sum(annual_billing, "swissgrid_cost_chf"),
        "Taxes": _safe_sum(annual_billing, "taxes_cost_chf"),
        "Fixes": _safe_sum(annual_billing, "fixed_cost_chf"),
    }
    visible = {label: value for label, value in values.items() if value is not None}
    if not visible:
        return None
    fig, ax = plt.subplots(figsize=(10.8, 2.8))
    labels = list(visible)
    amounts = list(visible.values())
    colors = ["#E0553A", "#F2A182", "#56606D", "#4C81C5", "#8E9AAF"]
    bars = ax.bar(labels, amounts, color=colors[: len(labels)])
    for bar, amount in zip(bars, amounts):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height(),
            f"{_fmt(amount)} CHF",
            ha="center",
            va="bottom",
            fontsize=7,
        )
    ax.set_ylabel("CHF", fontsize=8)
    ax.set_title("Composition du coût d'achat", fontsize=11, fontweight="bold", pad=8)
    ax.grid(axis="y", alpha=0.18)
    ax.tick_params(axis="both", labelsize=8)
    fig.tight_layout(pad=0.8)
    buffer = BytesIO()
    fig.savefig(buffer, format="png", dpi=165, bbox_inches="tight", pad_inches=0.03)
    plt.close(fig)
    buffer.seek(0)
    return buffer


def _period(data: pd.DataFrame) -> str:
    timestamps = pd.to_datetime(data["analysis_timestamp"])
    return f"{timestamps.min():%d.%m.%Y} - {timestamps.max():%d.%m.%Y}"


def _add_page(
    pdf: EnergyReportPDF,
    *,
    client_name: str,
    grd: str,
    offer: str,
    period: str,
) -> None:
    pdf.add_page()
    _sidebar(pdf, client_name=client_name, grd=grd, offer=offer, period=period)


def _page_summary(
    pdf: EnergyReportPDF,
    *,
    client_name: str,
    grd: str,
    offer: str,
    data: pd.DataFrame,
    metrics: dict[str, Any],
    annual_billing: pd.DataFrame,
    conclusion: str,
) -> None:
    period = _period(data)
    _add_page(pdf, client_name=client_name, grd=grd, offer=offer, period=period)
    x0 = 58
    pdf.set_xy(x0, 14)
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(*ORANGE)
    pdf.cell(142, 8, _tx("CONSEIL ÉNERGÉTIQUE"))
    pdf.set_xy(x0, 23)
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(*TEXT)
    pdf.cell(142, 6, _tx("Synthèse du profil photovoltaïque"))
    pdf.set_xy(x0, 33)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(*MUTED)
    pdf.multi_cell(142, 4, _tx(f"Données analysées : {period}"))
    pdf.set_draw_color(*BORDER)
    pdf.line(x0, 44, 202, 44)

    export_available = bool(metrics.get("export_available", True))
    import_total = _safe_sum(data, "import_kwh")
    export_total = _safe_sum(data, "export_kwh") if export_available else None
    ttc = _safe_sum(annual_billing, "net_estimated_cost_ttc_chf")
    cards = (
        ("Énergie achetée", f"{_fmt(import_total)} kWh", "Import réseau mesuré", BLUE),
        (
            "Surplus injecté",
            f"{_fmt(export_total)} kWh" if export_available else "Non fourni",
            "Injection réseau mesurée"
            if export_available
            else "À compléter pour la reprise PV",
            GREEN if export_available else RED,
        ),
        (
            "Import nocturne",
            f"{_fmt(metrics.get('night_import_kwh'))} kWh",
            "Fenêtre de référence 23 h - 6 h",
            BLUE,
        ),
        (
            "Potentiel de pilotage",
            f"{_fmt(metrics.get('shiftable_ceiling_kwh'))} kWh"
            if export_available
            else "À compléter",
            "Plafond théorique avant batterie"
            if export_available
            else "Injection réseau manquante",
            GREEN if export_available else RED,
        ),
        (
            "Coût estimé TTC",
            f"{_fmt(ttc)} CHF" if ttc is not None else "À compléter",
            "Selon les paramètres tarifaires disponibles",
            GREEN if ttc is not None else BLUE,
        ),
        (
            "Période analysée",
            f"{int(metrics.get('valid_days', 0))} jours",
            "Mesures réelles",
            BLUE,
        ),
    )
    _section_title(pdf, x0, 51, "RÉSULTATS PRINCIPAUX")
    width, gap, height = 45.5, 3.5, 31
    for index, card in enumerate(cards):
        row, column = divmod(index, 3)
        _metric_box(
            pdf,
            x0 + column * (width + gap),
            62 + row * 36,
            width,
            height,
            *card,
        )

    _section_title(pdf, x0, 140, "LECTURE SOLEOL")
    _info_box(pdf, x0, 151, 144, 34, "Priorité", conclusion, LIGHT_BLUE, BLUE)
    tariff_text = (
        f"{grd} - {offer}. Les plages HT/BT, frais fixes, composantes d'achat et "
        "reprise PV sont calculés séparément à partir des kWh mesurés."
    )
    _info_box(pdf, x0, 192, 144, 28, "Tarif appliqué", tariff_text, LIGHT_GREEN, GREEN)
    limits = (
        "Les flux réseau ne reconstituent pas la consommation totale du bâtiment ni la production "
        "PV totale. Les résultats ne sont pas annualisés lorsqu'une période est incomplète."
    )
    _info_box(pdf, x0, 227, 144, 28, "Limites de lecture", limits, LIGHT_RED, RED)


def _page_profile(
    pdf: EnergyReportPDF,
    *,
    client_name: str,
    grd: str,
    offer: str,
    data: pd.DataFrame,
    monthly: pd.DataFrame,
    export_available: bool,
) -> None:
    period = _period(data)
    _add_page(pdf, client_name=client_name, grd=grd, offer=offer, period=period)
    x0 = 58
    pdf.set_xy(x0, 14)
    pdf.set_font("Helvetica", "B", 17)
    pdf.set_text_color(*ORANGE)
    pdf.cell(142, 8, _tx("PROFIL ÉNERGÉTIQUE"))
    monthly_chart = _monthly_chart(monthly, export_available)
    seasonal_chart = _seasonal_chart(data, export_available)
    pdf.image(monthly_chart, x=x0, y=29, w=144, h=72)
    pdf.image(seasonal_chart, x=x0, y=108, w=144, h=106)
    message = (
        "Les courbes représentent une moyenne des mesures réelles. L'import est affiché au-dessus "
        "de zéro et l'injection au-dessous."
        if export_available
        else "Le fichier ne fournit pas l'injection réseau : le graphique montre les consommations "
        "mesurées, sans déduire de surplus photovoltaïque."
    )
    _info_box(pdf, x0, 222, 144, 30, "Comment lire ces graphiques", message, LIGHT_BLUE, BLUE)


def _page_actions(
    pdf: EnergyReportPDF,
    *,
    client_name: str,
    grd: str,
    offer: str,
    data: pd.DataFrame,
    annual_billing: pd.DataFrame,
    recommendations: list[dict[str, Any]],
    export_available: bool,
) -> None:
    period = _period(data)
    _add_page(pdf, client_name=client_name, grd=grd, offer=offer, period=period)
    x0 = 58
    pdf.set_xy(x0, 14)
    pdf.set_font("Helvetica", "B", 17)
    pdf.set_text_color(*ORANGE)
    pdf.cell(142, 8, _tx("PLAN D'ACTION"))
    billing = _billing_chart(annual_billing)
    if billing is not None:
        pdf.image(billing, x=x0, y=29, w=144, h=55)
        start_y = 92
    else:
        _info_box(
            pdf,
            x0,
            32,
            144,
            28,
            "Estimation tarifaire",
            "Les composantes tarifaires doivent être complétées avant de chiffrer le coût d'achat.",
            LIGHT_BLUE,
            BLUE,
        )
        start_y = 70

    _section_title(pdf, x0, start_y, "ACTIONS PRIORITAIRES")
    shown = recommendations[:3]
    y = start_y + 11
    for recommendation in shown:
        category = str(recommendation.get("category", "Conseil"))
        title = str(recommendation.get("title", ""))
        text = str(recommendation.get("text", ""))
        _info_box(pdf, x0, y, 144, 32, f"{category} - {title}", text, LIGHT_GREEN, GREEN)
        y += 37
    if not shown:
        _info_box(
            pdf,
            x0,
            y,
            144,
            30,
            "Étape suivante",
            "Rapprocher les courbes de charge des usages du site pour établir un plan de pilotage.",
            LIGHT_BLUE,
            BLUE,
        )
        y += 35
    note = (
        "La batterie est étudiée seulement après les mesures de pilotage et de programmation."
        if export_available
        else "L'injection réseau doit être ajoutée avant toute estimation de reprise PV ou de batterie."
    )
    _info_box(pdf, x0, min(y + 2, 250), 144, 24, "Suite recommandée", note, LIGHT_BLUE, BLUE)


def generate_energy_report(
    *,
    client_name: str,
    grd: str,
    offer: str,
    data: pd.DataFrame,
    monthly: pd.DataFrame,
    metrics: dict[str, Any],
    annual_billing: pd.DataFrame,
    recommendations: list[dict[str, Any]],
    conclusion: str,
) -> bytes:
    """Génère les trois pages du rapport client Soleol."""

    if data.empty:
        raise ValueError("Impossible de générer un rapport sans mesure exploitable.")
    pdf = EnergyReportPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=False)
    pdf.alias_nb_pages()
    export_available = bool(metrics.get("export_available", True))
    _page_summary(
        pdf,
        client_name=client_name,
        grd=grd,
        offer=offer,
        data=data,
        metrics=metrics,
        annual_billing=annual_billing,
        conclusion=conclusion,
    )
    _page_profile(
        pdf,
        client_name=client_name,
        grd=grd,
        offer=offer,
        data=data,
        monthly=monthly,
        export_available=export_available,
    )
    _page_actions(
        pdf,
        client_name=client_name,
        grd=grd,
        offer=offer,
        data=data,
        annual_billing=annual_billing,
        recommendations=recommendations,
        export_available=export_available,
    )
    output = pdf.output()
    return bytes(output) if isinstance(output, (bytes, bytearray)) else output.encode("latin-1")
