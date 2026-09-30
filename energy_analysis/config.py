"""Paramètres explicites et faciles à adapter pour l'analyse."""

from dataclasses import dataclass

BRAND_ORANGE = "#E0553A"
IMPORT_COLOR = "#E0553A"
EXPORT_COLOR = "#45B7A8"
TEXT_COLOR = "#F4F4F4"
MUTED_TEXT_COLOR = "#B7B7B7"
PAPER_COLOR = "#111315"
PLOT_COLOR = "#181B1F"
GRID_COLOR = "#31363D"

SEASONS = {
    "Printemps": (3, 4, 5),
    "Été": (6, 7, 8),
    "Automne": (9, 10, 11),
    "Hiver": (12, 1, 2),
}
SEASON_ORDER = tuple(SEASONS)


@dataclass(frozen=True)
class AnalysisSettings:
    """Réglages de lecture. Les valeurs par défaut correspondent au conseil PV."""

    night_start_hour: int = 23
    night_end_hour: int = 6
    solar_start_hour: int = 10
    solar_end_hour: int = 16
    noise_kw: float = 0.10
    recurring_min_days: int = 10
    recurring_min_ratio: float = 0.25
    timestamp_convention: str = "end"


DEFAULT_SETTINGS = AnalysisSettings()
