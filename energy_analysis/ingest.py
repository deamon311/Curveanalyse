"""Lecture et normalisation prudente des courbes de charge Excel."""

from __future__ import annotations

import calendar
import math
import re
import unicodedata
from pathlib import Path
from typing import BinaryIO

import numpy as np
import pandas as pd

from .models import DataQuality, ImportedFile

IMPORT_KEYWORDS = ("soutirage", "import", "prelevement", "prelev", "achat reseau")
EXPORT_KEYWORDS = ("surplus", "export", "injection", "reinjection", "production injectee")
METER_METADATA = {
    "adresse": "Adresse",
    "lieu de consommation": "Adresse",
    "designation": "Objet",
    "objet": "Objet",
    "numero de compteur": "Compteur",
}


def normalize_text(value: object) -> str:
    """Normalise les accents et espaces afin de rendre la détection tolérante."""

    if pd.isna(value):
        return ""
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", text).strip().lower()


def _source_name(file_obj: str | Path | BinaryIO) -> str:
    name = getattr(file_obj, "name", None)
    return Path(name or str(file_obj)).name


def find_header_row(raw: pd.DataFrame) -> int:
    """Trouve l'en-tête contenant la date et au moins un flux réseau."""

    for row_index in range(min(len(raw), 80)):
        values = [normalize_text(value) for value in raw.iloc[row_index].tolist()]
        has_date = any(value == "date" or "date" in value for value in values)
        has_import = any(
            any(keyword in value for keyword in IMPORT_KEYWORDS) for value in values
        )
        has_export = any(
            any(keyword in value for keyword in EXPORT_KEYWORDS) for value in values
        )
        if has_date and (has_import or has_export):
            return row_index
    raise ValueError(
        "Impossible de trouver une ligne d'en-tête contenant Date et "
        "Soutirage/Import ou Surplus/Export."
    )


def identify_columns(columns: pd.Index) -> tuple[object, object | None, object | None]:
    """Identifie les colonnes Date, import et export à partir de leur libellé."""

    date_col = import_col = export_col = None
    for column in columns:
        label = normalize_text(column)
        if date_col is None and "date" in label:
            date_col = column
        if import_col is None and any(keyword in label for keyword in IMPORT_KEYWORDS):
            import_col = column
        if export_col is None and any(keyword in label for keyword in EXPORT_KEYWORDS):
            export_col = column
    if date_col is None:
        raise ValueError("Colonne de date introuvable.")
    if import_col is None and export_col is None:
        raise ValueError("Aucune colonne de soutirage/import ou de surplus/export trouvée.")
    return date_col, import_col, export_col


def infer_column_unit(column: object | None) -> str:
    """Retourne power, energy ou unknown selon le libellé de colonne."""

    label = normalize_text(column)
    compact = re.sub(r"[^a-z0-9]", "", label)
    if "kwh" in compact:
        return "energy"
    if "kw" in compact:
        return "power"
    return "unknown"


def numeric_series(values: pd.Series) -> pd.Series:
    """Accepte notamment les formats suisses 1'234,56."""

    if pd.api.types.is_numeric_dtype(values):
        return pd.to_numeric(values, errors="coerce")
    cleaned = (
        values.astype(str)
        .str.replace("\u00a0", "", regex=False)
        .str.replace("\u202f", "", regex=False)
        .str.replace(" ", "", regex=False)
        .str.replace("'", "", regex=False)
        .str.replace(",", ".", regex=False)
    )
    return pd.to_numeric(cleaned, errors="coerce")


def infer_nominal_interval_hours(timestamps: pd.Series) -> float:
    """Détecte le pas nominal sans intégrer artificiellement les trous."""

    diffs_minutes = (
        timestamps.sort_values().drop_duplicates().diff().dropna().dt.total_seconds().div(60)
    )
    plausible = diffs_minutes[(diffs_minutes > 0) & (diffs_minutes <= 360)]
    if plausible.empty:
        return 0.25
    modes = plausible.round(6).mode()
    minutes = float(modes.iloc[0]) if not modes.empty else float(plausible.median())
    return minutes / 60 if minutes > 0 else 0.25


def extract_metadata(raw: pd.DataFrame) -> dict[str, str]:
    """Récupère les informations client usuelles présentes au-dessus de l'en-tête."""

    metadata: dict[str, str] = {}
    for _, row in raw.iloc[:12].iterrows():
        values = [value for value in row.tolist() if not pd.isna(value)]
        if len(values) < 2:
            continue
        label = normalize_text(values[0])
        value = str(values[1]).strip()
        for needle, key in METER_METADATA.items():
            if needle in label and key not in metadata and value:
                metadata[key] = value
    return metadata


def _read_sheet(workbook: pd.ExcelFile, sheet_name: str, source_name: str) -> ImportedFile:
    raw = pd.read_excel(workbook, sheet_name=sheet_name, header=None, nrows=80)
    header_row = find_header_row(raw)
    table = pd.read_excel(workbook, sheet_name=sheet_name, header=header_row)
    table = table.dropna(how="all").copy()
    date_col, import_col, export_col = identify_columns(table.columns)

    timestamp = pd.to_datetime(table[date_col], errors="coerce")
    out = pd.DataFrame({"timestamp": timestamp})
    out = out.dropna(subset=["timestamp"]).copy()
    source_rows = table.index.to_series().loc[out.index].astype(int) + header_row + 2

    warnings: list[str] = []
    invalid_count = 0
    units = []

    def normalise_flux(
        column: object | None, prefix: str
    ) -> tuple[pd.Series, pd.Series, pd.Series]:
        nonlocal invalid_count
        if column is None:
            return (
                pd.Series(0.0, index=out.index, dtype=float),
                pd.Series(0.0, index=out.index, dtype=float),
                pd.Series(True, index=out.index, dtype=bool),
            )
        unit = infer_column_unit(column)
        units.append(unit)
        values = numeric_series(table.loc[out.index, column])
        valid = values.notna()
        invalid_count += int((~valid).sum())
        values = values.astype(float)
        if (values < 0).any():
            warnings.append(
                f"{prefix}: {int((values < 0).sum())} valeur(s) négative(s) ont été "
                "traitées comme invalides : vérifiez la convention de signe."
            )
            valid &= values >= 0
            values = values.where(values >= 0)
        return values, pd.Series(unit, index=out.index, dtype="object"), valid

    import_values, import_units, import_valid = normalise_flux(import_col, "Soutirage")
    export_values, export_units, export_valid = normalise_flux(export_col, "Surplus")
    interval_h = infer_nominal_interval_hours(out["timestamp"])

    # Si une colonne est explicitement en kWh, la valeur est déjà une énergie
    # par intervalle. Sinon, les kWh sont calculés avec le pas nominal détecté.
    def make_energy(values: pd.Series, units: pd.Series) -> tuple[pd.Series, pd.Series]:
        is_energy = units.eq("energy")
        kwh = np.where(is_energy, values, values * interval_h)
        kw = np.where(is_energy, values / interval_h, values)
        return (
            pd.Series(kwh, index=out.index, dtype=float),
            pd.Series(kw, index=out.index, dtype=float),
        )

    import_kwh, import_kw = make_energy(import_values, import_units)
    export_kwh, export_kw = make_energy(export_values, export_units)

    out["import_kw"] = import_kw
    out["export_kw"] = export_kw
    out["import_kwh"] = import_kwh
    out["export_kwh"] = export_kwh
    out["import_valid"] = import_valid
    out["export_valid"] = export_valid
    out["valid_measurement"] = import_valid & export_valid
    out["interval_h"] = interval_h
    out["source_file"] = source_name
    out["sheet_name"] = str(sheet_name)
    out["source_row"] = source_rows
    out["input_unit"] = "kWh par intervalle" if "energy" in units else "kW moyen par intervalle"

    if "unknown" in units:
        warnings.append(
            "Unité absente du libellé de colonne : les valeurs ont été interprétées "
            "comme des puissances en kW."
        )
    if invalid_count:
        warnings.append(
            f"{invalid_count} valeur(s) non numériques ou incompatibles ont été "
            "exclues des calculs correspondants."
        )
    return ImportedFile(
        data=out.reset_index(drop=True),
        source_name=source_name,
        sheet_name=str(sheet_name),
        metadata=extract_metadata(raw),
        warnings=warnings,
        nominal_interval_h=interval_h,
        invalid_numeric_values=invalid_count,
    )


def read_energy_file(file_obj: str | Path | BinaryIO) -> ImportedFile:
    """Lit le premier onglet Excel compatible et retourne la table canonique."""

    if hasattr(file_obj, "seek"):
        file_obj.seek(0)
    source_name = _source_name(file_obj)
    workbook = pd.ExcelFile(file_obj, engine="openpyxl")
    errors: list[str] = []
    for sheet_name in workbook.sheet_names:
        try:
            return _read_sheet(workbook, sheet_name, source_name)
        except ValueError as exc:
            errors.append(f"{sheet_name}: {exc}")
    detail = " | ".join(errors[:3])
    raise ValueError(f"{source_name}: aucun onglet compatible. {detail}")


def _is_swiss_dst_forward_gap(
    previous: pd.Timestamp, current: pd.Timestamp, nominal_minutes: float
) -> bool:
    """Repère le saut CET → CEST dans des horodatages Excel sans fuseau."""

    if current.month != 3 or current.weekday() != 6 or current.hour != 3:
        return False
    last_day = calendar.monthrange(current.year, 3)[1]
    last_sunday = max(
        day
        for day in range(1, last_day + 1)
        if pd.Timestamp(current.year, 3, day).weekday() == 6
    )
    if current.day != last_sunday:
        return False
    gap_minutes = (current - previous).total_seconds() / 60
    return abs(gap_minutes - (nominal_minutes + 60)) < 0.1


def _gap_stats(data: pd.DataFrame) -> tuple[int, int, int]:
    """Compte les lacunes à partir du pas nominal de chaque source."""

    gap_events = 0
    missing = 0
    dst_forward_events = 0
    for _, source in data.groupby(["source_file", "sheet_name"], dropna=False):
        ordered = source.sort_values("timestamp")
        nominal_minutes = max(float(ordered["interval_h"].iloc[0]) * 60, 0.001)
        timestamps = ordered["timestamp"].tolist()
        for previous, current in zip(timestamps, timestamps[1:]):
            gap_minutes = (current - previous).total_seconds() / 60
            if gap_minutes <= nominal_minutes * 1.5:
                continue
            if _is_swiss_dst_forward_gap(previous, current, nominal_minutes):
                dst_forward_events += 1
                continue
            gap_events += 1
            missing += max(0, math.floor(gap_minutes / nominal_minutes) - 1)
    return gap_events, missing, dst_forward_events


def combine_imports(imported_files: list[ImportedFile]) -> tuple[pd.DataFrame, DataQuality]:
    """Fusionne plusieurs fichiers sans double comptage et avec une trace qualité."""

    if not imported_files:
        raise ValueError("Aucun fichier à fusionner.")
    data = pd.concat([item.data for item in imported_files], ignore_index=True)
    data = data.sort_values(
        ["timestamp", "source_file", "sheet_name", "source_row"]
    ).reset_index(drop=True)
    quality = DataQuality(imported_rows=len(data))
    gap_events, missing_intervals, dst_forward_events = _gap_stats(data)
    quality.gap_events = gap_events
    quality.estimated_missing_intervals = missing_intervals
    quality.daylight_saving_forward_events = dst_forward_events

    identical = conflicting = 0
    for _, group in data.groupby("timestamp", sort=False):
        if len(group) <= 1:
            continue
        values = group[["import_kw", "export_kw", "import_kwh", "export_kwh"]].to_numpy()
        if np.allclose(values, values[0], rtol=1e-8, atol=1e-8, equal_nan=True):
            identical += len(group) - 1
        else:
            conflicting += len(group) - 1
    quality.identical_duplicates = identical
    quality.conflicting_duplicates = conflicting

    # Règle déterministe : les sources sont triées par nom puis ligne ; conserver
    # la dernière évite que l'ordre de téléversement ne change le résultat.
    combined = data.drop_duplicates(subset=["timestamp"], keep="last").copy()
    combined = combined.sort_values("timestamp").reset_index(drop=True)
    quality.retained_rows = len(combined)
    quality.invalid_numeric_values = sum(item.invalid_numeric_values for item in imported_files)
    quality.warnings.extend(warning for item in imported_files for warning in item.warnings)
    if identical:
        quality.warnings.append(f"{identical} doublon(s) identique(s) ont été supprimés.")
    if conflicting:
        quality.warnings.append(
            f"{conflicting} doublon(s) contradictoire(s) détecté(s) : la valeur issue "
            "du fichier classé en dernier par nom a été conservée. Vérifiez les sources."
        )
    if missing_intervals:
        quality.warnings.append(
            f"{missing_intervals} pas de mesure estimé(s) manquant(s) ont été détectés. "
            "Aucune énergie n'a été extrapolée sur ces lacunes."
        )
    if dst_forward_events:
        quality.warnings.append(
            "Le passage à l’heure d’été a été détecté. Les pas horaires absents "
            "lors de ce changement ne sont pas comptés comme une lacune de données."
        )
    quality.source_rows = [
        {
            "Fichier": item.source_name,
            "Feuille": item.sheet_name,
            "Mesures lues": len(item.data),
            "Mesures exploitables": int(item.data["valid_measurement"].sum()),
            "Pas détecté": f"{item.nominal_interval_h * 60:.0f} min",
            "Unité": item.data["input_unit"].iloc[0],
        }
        for item in imported_files
    ]
    return combined, quality


def apply_timestamp_convention(data: pd.DataFrame, convention: str = "end") -> pd.DataFrame:
    """Crée l'horodatage utilisé pour les regroupements, sans modifier l'énergie."""

    result = data.copy()
    if convention not in {"end", "start"}:
        raise ValueError("Convention d'horodatage inconnue.")
    if convention == "end":
        result["analysis_timestamp"] = result["timestamp"] - pd.to_timedelta(
            result["interval_h"], unit="h"
        )
    else:
        result["analysis_timestamp"] = result["timestamp"]
    result["year"] = result["analysis_timestamp"].dt.year
    result["month"] = result["analysis_timestamp"].dt.month
    result["month_label"] = result["analysis_timestamp"].dt.strftime("%Y-%m")
    result["day"] = result["analysis_timestamp"].dt.date
    result["minute_of_day"] = (
        result["analysis_timestamp"].dt.hour * 60 + result["analysis_timestamp"].dt.minute
    )
    return result
