"""Lecture et normalisation prudente des courbes Excel et CSV."""

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

IMPORT_KEYWORDS = (
    "soutirage",
    "import",
    "prelevement",
    "prelev",
    "achat reseau",
    "netzstrom",
    "netzbezug",
    "strombezug",
    "bezug",
)
EXPORT_KEYWORDS = (
    "surplus",
    "export",
    "injection",
    "reinjection",
    "production injectee",
    "excedent",
    "rucklieferung",
    "ruckspeisung",
    "einspeisung",
)
DATE_KEYWORDS = ("date", "datum")
METER_METADATA = {
    "adresse": "Adresse",
    "addresse": "Adresse",
    "lieu de consommation": "Adresse",
    "bezugstelle": "Adresse",
    "designation": "Objet",
    "objet": "Objet",
    "objektbezeichnung": "Objet",
    "numero de compteur": "Compteur",
    "zahlernummer": "Compteur",
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


def _compact_label(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", normalize_text(value))


def _is_autoconsumption_label(value: object) -> bool:
    return "autoconsommation" in _compact_label(value)


def _is_total_consumption_label(value: object) -> bool:
    return "consommationtotale" in _compact_label(value)


def _is_import_label(value: object) -> bool:
    label = normalize_text(value)
    compact = _compact_label(value)
    return any(keyword in label for keyword in IMPORT_KEYWORDS) or (
        compact.startswith("consommation")
        and not _is_autoconsumption_label(value)
        and not _is_total_consumption_label(value)
    )


def _is_export_label(value: object) -> bool:
    label = normalize_text(value)
    return any(keyword in label for keyword in EXPORT_KEYWORDS)


def _is_date_label(value: object) -> bool:
    label = normalize_text(value)
    return any(keyword == label or keyword in label for keyword in DATE_KEYWORDS)


def find_header_row(raw: pd.DataFrame) -> int:
    """Trouve l'en-tête FR/DE contenant la date et au moins un flux réseau."""

    for row_index in range(min(len(raw), 80)):
        values = [normalize_text(value) for value in raw.iloc[row_index].tolist()]
        has_date = any(_is_date_label(value) for value in values)
        has_import = any(_is_import_label(value) for value in values)
        has_export = any(_is_export_label(value) for value in values)
        if has_date and (has_import or has_export):
            return row_index
    raise ValueError(
        "Impossible de trouver une ligne d'en-tête contenant Date/Datum et "
        "Soutirage/Import/Netzbezug ou Surplus/Export/Rücklieferung."
    )


def identify_columns(columns: pd.Index) -> tuple[object, object | None, object | None]:
    """Identifie les colonnes Date, import et export à partir de leur libellé."""

    date_col = import_col = export_col = None
    for column in columns:
        label = normalize_text(column)
        if date_col is None and _is_date_label(label):
            date_col = column
        if import_col is None and _is_import_label(label):
            import_col = column
        if export_col is None and _is_export_label(label):
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
    # Les exports CSV Romande Energie nomment les colonnes « Consommation »
    # et « Excédent » sans unité. Les valeurs sont des kWh par pas de 15 min.
    if compact.startswith("consommation") or compact.startswith("excedent"):
        return "energy"
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


def _parse_timestamps(values: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Retourne l'instant unique et l'horloge locale Europe/Zurich.

    Les exports Romande Energie indiquent un offset UTC. L'instant UTC sert aux
    doublons et aux lacunes, tandis que l'horloge locale sert aux horaires GRD.
    Cela préserve les quatre quarts d'heure répétés au passage à l'heure d'hiver.
    """

    text = values.astype(str)
    has_offset = text.str.contains(r"(?:Z|[+-]\d{2}:\d{2})$", regex=True, na=False).any()
    if has_offset:
        parsed = pd.to_datetime(values, errors="coerce", utc=True)
        return (
            parsed.dt.tz_localize(None),
            parsed.dt.tz_convert("Europe/Zurich").dt.tz_localize(None),
        )
    parsed = pd.to_datetime(values, errors="coerce")
    return parsed, parsed


def _normalise_table(
    raw: pd.DataFrame,
    table: pd.DataFrame,
    source_name: str,
    sheet_name: str,
    header_row: int,
    *,
    unit_override: str | None = None,
    source_format: str = "Excel",
) -> ImportedFile:
    """Convertit une table fournisseur en format canonique de l'application."""

    table = table.dropna(how="all").copy()
    date_col, import_col, export_col = identify_columns(table.columns)

    timestamp, local_timestamp = _parse_timestamps(table[date_col])
    out = pd.DataFrame({"timestamp": timestamp, "local_timestamp": local_timestamp})
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
                pd.Series(np.nan, index=out.index, dtype=float),
                pd.Series("missing", index=out.index, dtype="object"),
                pd.Series(False, index=out.index, dtype=bool),
            )
        unit = unit_override or infer_column_unit(column)
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
    out["import_available"] = import_col is not None
    out["export_available"] = export_col is not None
    # Les export CSV Romande Energie commencent à 00:00 et finissent à 23:45 :
    # ils datent le début du pas. Les courbes Groupe E restent au format fin
    # d'intervalle, sans jamais exposer ce choix dans l'interface.
    out["timestamp_convention"] = "start" if source_format == "Romande Energie CSV" else "end"
    # Un fichier peut parfaitement ne contenir qu'un seul flux. La qualité de
    # lecture porte alors sur ce flux disponible, sans inventer l'autre.
    out["valid_measurement"] = import_valid | export_valid

    autoconsumption_col = next(
        (column for column in table.columns if _is_autoconsumption_label(column)), None
    )
    total_consumption_col = next(
        (column for column in table.columns if _is_total_consumption_label(column)), None
    )
    for column, prefix, key in (
        (autoconsumption_col, "Autoconsommation", "autoconsumption"),
        (total_consumption_col, "Consommation totale", "total_consumption"),
    ):
        values, value_units, valid = normalise_flux(column, prefix)
        kwh_values, kw_values = make_energy(values, value_units)
        out[f"{key}_kwh"] = kwh_values
        out[f"{key}_kw"] = kw_values
        out[f"{key}_valid"] = valid
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
    if import_col is None:
        warnings.append(
            "Le fichier ne contient pas de soutirage réseau : les analyses de consommation "
            "réseau restent indisponibles."
        )
    if export_col is None:
        warnings.append(
            "Le fichier ne contient pas d’injection réseau : la reprise PV et le potentiel "
            "de décalage solaire ne sont pas chiffrés."
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
        metadata={**extract_metadata(raw), "Format": source_format},
        warnings=warnings,
        nominal_interval_h=interval_h,
        invalid_numeric_values=invalid_count,
    )


def _read_sheet(
    workbook: pd.ExcelFile,
    sheet_name: str,
    source_name: str,
    *,
    unit_override: str | None = None,
) -> ImportedFile:
    raw = pd.read_excel(workbook, sheet_name=sheet_name, header=None, nrows=80)
    header_row = find_header_row(raw)
    table = pd.read_excel(workbook, sheet_name=sheet_name, header=header_row)
    return _normalise_table(
        raw,
        table,
        source_name,
        sheet_name,
        header_row,
        unit_override=unit_override,
        source_format="Excel",
    )


def _read_csv(
    file_obj: str | Path | BinaryIO,
    source_name: str,
    *,
    unit_override: str | None = None,
) -> ImportedFile:
    """Lit les exports CSV, notamment les courbes Romande Energie au pas de 15 min."""

    if hasattr(file_obj, "seek"):
        file_obj.seek(0)
    raw = pd.read_csv(file_obj, sep=None, engine="python", header=None, nrows=80)
    header_row = find_header_row(raw)
    if hasattr(file_obj, "seek"):
        file_obj.seek(0)
    table = pd.read_csv(file_obj, sep=None, engine="python", header=header_row)
    is_romande = any("consommation" in _compact_label(column) for column in table.columns)
    return _normalise_table(
        raw,
        table,
        source_name,
        "CSV",
        header_row,
        unit_override=unit_override or ("energy" if is_romande else None),
        source_format="Romande Energie CSV" if is_romande else "CSV",
    )


def read_energy_file(
    file_obj: str | Path | BinaryIO,
    *,
    grd: str | None = None,
) -> ImportedFile:
    """Lit une courbe Excel ou CSV et retourne la table canonique.

    Règle métier Soleol : les courbes Groupe E sont en kW et les courbes
    Romande Energie sont en kWh par intervalle. Le GRD sélectionné dans
    l'interface impose donc l'unité avant tout calcul.
    """

    if hasattr(file_obj, "seek"):
        file_obj.seek(0)
    source_name = _source_name(file_obj)
    unit_override = {"Groupe E": "power", "Romande Energie": "energy"}.get(grd)
    if Path(source_name).suffix.lower() == ".csv":
        return _read_csv(file_obj, source_name, unit_override=unit_override)
    workbook = pd.ExcelFile(file_obj, engine="openpyxl")
    errors: list[str] = []
    for sheet_name in workbook.sheet_names:
        try:
            return _read_sheet(
                workbook,
                sheet_name,
                source_name,
                unit_override=unit_override,
            )
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


def apply_timestamp_convention(data: pd.DataFrame) -> pd.DataFrame:
    """Applique automatiquement la convention propre au format fournisseur.

    Groupe E est traité comme une fin d'intervalle. Les CSV Romande Energie
    sont traités comme un début d'intervalle, selon leur couverture 00:00–23:45.
    L'utilisateur ne choisit jamais cette règle et l'énergie mesurée ne change pas.
    """

    result = data.copy()
    clock_timestamp = result.get("local_timestamp", result["timestamp"])
    conventions = result.get(
        "timestamp_convention", pd.Series("end", index=result.index, dtype="object")
    )
    end_interval = conventions.eq("end")
    result["analysis_timestamp"] = clock_timestamp
    result.loc[end_interval, "analysis_timestamp"] = clock_timestamp.loc[
        end_interval
    ] - pd.to_timedelta(result.loc[end_interval, "interval_h"], unit="h")
    result["year"] = result["analysis_timestamp"].dt.year
    result["month"] = result["analysis_timestamp"].dt.month
    result["month_label"] = result["analysis_timestamp"].dt.strftime("%Y-%m")
    result["day"] = result["analysis_timestamp"].dt.date
    result["minute_of_day"] = (
        result["analysis_timestamp"].dt.hour * 60 + result["analysis_timestamp"].dt.minute
    )
    return result
