"""Objets de transport légers, séparés de l'interface Streamlit."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass
class ImportedFile:
    """Un fichier Excel normalisé sans appliquer la convention horaire finale."""

    data: pd.DataFrame
    source_name: str
    sheet_name: str
    metadata: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    nominal_interval_h: float = 0.25
    invalid_numeric_values: int = 0


@dataclass
class DataQuality:
    """Informations à montrer au conseiller pour rendre l'analyse traçable."""

    imported_rows: int = 0
    retained_rows: int = 0
    identical_duplicates: int = 0
    conflicting_duplicates: int = 0
    gap_events: int = 0
    estimated_missing_intervals: int = 0
    daylight_saving_forward_events: int = 0
    invalid_numeric_values: int = 0
    source_rows: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
