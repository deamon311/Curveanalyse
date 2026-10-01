"""Calculs d'énergie et d'analyse de profil, sans dépendance à Streamlit."""

from __future__ import annotations

from calendar import monthrange
from collections.abc import Iterable

import numpy as np
import pandas as pd

from .config import SEASON_ORDER, SEASONS, AnalysisSettings
from .formatting import MONTH_NAMES, time_label

MIN_COMPARABLE_QUARTER_HOURS = 96


def _window_mask(minutes: pd.Series, start_hour: int, end_hour: int) -> pd.Series:
    """Fenêtre horaire [début, fin), y compris lorsqu'elle traverse minuit."""

    start = int(start_hour) * 60
    end = int(end_hour) * 60
    if start == end:
        return pd.Series(True, index=minutes.index)
    if start < end:
        return (minutes >= start) & (minutes < end)
    return (minutes >= start) | (minutes < end)


def add_analysis_flags(data: pd.DataFrame, settings: AnalysisSettings) -> pd.DataFrame:
    """Ajoute les fenêtres utilisées par les indicateurs de pilotage."""

    result = data.copy()
    minutes = result["minute_of_day"]
    result["is_night"] = _window_mask(
        minutes, settings.night_start_hour, settings.night_end_hour
    )
    result["is_solar_window"] = _window_mask(
        minutes, settings.solar_start_hour, settings.solar_end_hour
    )
    result["is_outside_solar_window"] = ~result["is_solar_window"]
    month_to_season = {month: season for season, months in SEASONS.items() for month in months}
    result["season"] = result["month"].map(month_to_season)
    return result


def _coverage(first: pd.Timestamp, last: pd.Timestamp, count: int, interval_h: float) -> float:
    if pd.isna(first) or pd.isna(last) or interval_h <= 0:
        return float("nan")
    interval_minutes = max(1, round(interval_h * 60))
    first_day = first.normalize()
    last_day = last.normalize()
    days = (last_day - first_day).days + 1
    expected = max(1, round(days * 24 * 60 / interval_minutes))
    return min(1.0, count / expected)


def _peak_time(group: pd.DataFrame, column: str) -> pd.Timestamp | pd.NaT:
    if group.empty or group[column].isna().all():
        return pd.NaT
    # Les CSV Romande Energie possèdent un instant UTC canonique et une heure
    # locale : citer l'heure locale du fournisseur au client.
    timestamp_column = "local_timestamp" if "local_timestamp" in group.columns else "timestamp"
    return group.loc[group[column].idxmax(), timestamp_column]


def annual_summary(data: pd.DataFrame) -> pd.DataFrame:
    """Synthèse annuelle avec période et taux de couverture réels."""

    rows: list[dict[str, object]] = []
    for year, group in data.groupby("year", sort=True):
        first = group["analysis_timestamp"].min()
        last = group["analysis_timestamp"].max()
        interval_h = float(group["interval_h"].median())
        valid_count = int(group["valid_measurement"].sum())
        coverage = _coverage(first, last, valid_count, interval_h)
        calendar_complete = (
            first.month == 1 and first.day == 1 and last.month == 12 and last.day == 31
        )
        if calendar_complete:
            period_status = (
                "Année complète" if coverage >= 0.98 else "Année complète — données incomplètes"
            )
        else:
            period_status = f"Partielle : {first:%d.%m.%Y} – {last:%d.%m.%Y}"
        rows.append(
            {
                "year": int(year),
                "import_kwh": group["import_kwh"].sum(min_count=1),
                "export_kwh": group["export_kwh"].sum(min_count=1),
                "balance_kwh": group["import_kwh"].sum(min_count=1)
                - group["export_kwh"].sum(min_count=1),
                "peak_import_kw": group["import_kw"].max(),
                "peak_export_kw": group["export_kw"].max(),
                "peak_import_at": _peak_time(group, "import_kw"),
                "peak_export_at": _peak_time(group, "export_kw"),
                "first": first,
                "last": last,
                "measurements": valid_count,
                "interval_h": interval_h,
                "coverage": coverage,
                "period_status": period_status,
            }
        )
    return pd.DataFrame(rows)


def monthly_summary(data: pd.DataFrame) -> pd.DataFrame:
    """Synthèse par mois en conservant séparément les années."""

    rows: list[dict[str, object]] = []
    for (year, month), group in data.groupby(["year", "month"], sort=True):
        first = group["analysis_timestamp"].min()
        last = group["analysis_timestamp"].max()
        interval_h = float(group["interval_h"].median())
        expected = round(monthrange(int(year), int(month))[1] * 24 / interval_h)
        valid_count = int(group["valid_measurement"].sum())
        rows.append(
            {
                "year": int(year),
                "month": int(month),
                "month_name": MONTH_NAMES[int(month)],
                "label": f"{MONTH_NAMES[int(month)][:3]} {int(year)}",
                "import_kwh": group["import_kwh"].sum(min_count=1),
                "export_kwh": group["export_kwh"].sum(min_count=1),
                "balance_kwh": group["import_kwh"].sum(min_count=1)
                - group["export_kwh"].sum(min_count=1),
                "peak_import_kw": group["import_kw"].max(),
                "peak_export_kw": group["export_kw"].max(),
                "measurements": valid_count,
                "coverage": min(1.0, valid_count / max(1, expected)),
                "first": first,
                "last": last,
            }
        )
    return pd.DataFrame(rows)


def comparable_years(
    data: pd.DataFrame, current_year: int, previous_year: int
) -> tuple[pd.DataFrame, dict[str, object] | None]:
    """Compare deux années seulement sur une journée commune exploitable.

    Une simple mesure située de part et d'autre du changement d'année ne doit
    pas produire une comparaison N/N-1. Les courbes Soleol sont au quart
    d'heure : 96 pas communs correspondent donc au minimum à une journée de
    référence avant d'afficher une évolution au client.
    """

    current = data[(data["year"] == current_year) & data["valid_measurement"]].copy()
    previous = data[(data["year"] == previous_year) & data["valid_measurement"]].copy()
    if current.empty or previous.empty:
        return pd.DataFrame(), None
    key_columns = ["month", "analysis_day", "minute_of_day"]
    current["analysis_day"] = current["analysis_timestamp"].dt.day
    previous["analysis_day"] = previous["analysis_timestamp"].dt.day
    current_keys = pd.MultiIndex.from_frame(current[key_columns])
    previous_keys = pd.MultiIndex.from_frame(previous[key_columns])
    common_keys = current_keys.intersection(previous_keys)
    if len(common_keys) < MIN_COMPARABLE_QUARTER_HOURS:
        return pd.DataFrame(), None
    current = current.set_index(key_columns).loc[common_keys].reset_index()
    previous = previous.set_index(key_columns).loc[common_keys].reset_index()
    rows = []
    for year, group in ((previous_year, previous), (current_year, current)):
        rows.append(
            {
                "year": year,
                "import_kwh": group["import_kwh"].sum(min_count=1),
                "export_kwh": group["export_kwh"].sum(min_count=1),
                "balance_kwh": group["import_kwh"].sum(min_count=1)
                - group["export_kwh"].sum(min_count=1),
                "peak_import_kw": group["import_kw"].max(),
                "peak_export_kw": group["export_kw"].max(),
                "measurements": len(group),
            }
        )
    first = current["analysis_timestamp"].min()
    last = current["analysis_timestamp"].max()
    info = {
        "first": first,
        "last": last,
        "measurements": len(current),
        "days": current["analysis_timestamp"].dt.date.nunique(),
    }
    return pd.DataFrame(rows), info


def profile_metrics(data: pd.DataFrame, settings: AnalysisSettings) -> dict[str, object]:
    """Mesures prudentes destinées à prioriser le pilotage avant le stockage."""

    data = data[data["valid_measurement"]].copy()
    if data.empty:
        return {}
    import_available = bool(
        data.get("import_available", data["import_valid"]).fillna(False).any()
    )
    export_available = bool(
        data.get("export_available", data["export_valid"]).fillna(False).any()
    )
    night = data[data["is_night"]]
    solar = data[data["is_solar_window"]]
    outside_solar = data[data["is_outside_solar_window"]]
    active_export = solar[solar["export_kw"] > settings.noise_kw]
    valid_days = max(1, data["day"].nunique())

    daily = (
        data.assign(
            export_solar_kwh=np.where(data["is_solar_window"], data["export_kwh"], 0.0),
            import_outside_solar_kwh=np.where(
                data["is_outside_solar_window"], data["import_kwh"], 0.0
            ),
            import_night_kwh=np.where(data["is_night"], data["import_kwh"], 0.0),
        )
        .groupby("day", as_index=False)
        .agg(
            export_solar_kwh=("export_solar_kwh", "sum"),
            import_outside_solar_kwh=("import_outside_solar_kwh", "sum"),
            import_night_kwh=("import_night_kwh", "sum"),
        )
    )
    daily["shiftable_ceiling_kwh"] = np.minimum(
        daily["export_solar_kwh"], daily["import_outside_solar_kwh"]
    )
    overlap_days = (
        (daily["export_solar_kwh"] > 0.01) & (daily["import_outside_solar_kwh"] > 0.01)
    ).sum()

    hours_above = {
        threshold: float(data.loc[data["export_kw"] > threshold, "interval_h"].sum())
        for threshold in (1, 2, 3, 5)
    }
    export_active_hours = float(active_export["interval_h"].sum())
    export_active_average_kw = (
        float(active_export["export_kwh"].sum() / export_active_hours)
        if export_active_hours
        else 0.0
    )
    night_hours = float(night["interval_h"].sum())
    night_average_kw = float(night["import_kwh"].sum() / night_hours) if night_hours else 0.0

    seasons: dict[str, dict[str, float]] = {}
    for season in SEASON_ORDER:
        group = data[data["season"] == season]
        days = max(1, group["day"].nunique())
        seasons[season] = {
            "export_kwh": float(group["export_kwh"].sum()),
            "export_kwh_per_day": float(group["export_kwh"].sum() / days),
            "import_kwh": float(group["import_kwh"].sum()),
            "days": float(days),
        }

    return {
        "import_available": import_available,
        "export_available": export_available,
        "valid_days": valid_days,
        "import_total_kwh": float(data["import_kwh"].sum()),
        "export_total_kwh": float(data["export_kwh"].sum()),
        "night_import_kwh": float(night["import_kwh"].sum()),
        "night_import_kwh_per_day": float(night["import_kwh"].sum() / valid_days),
        "night_import_share": float(night["import_kwh"].sum() / data["import_kwh"].sum())
        if data["import_kwh"].sum()
        else 0.0,
        "night_average_kw": night_average_kw,
        "night_persistence_ratio": float((night["import_kw"] > settings.noise_kw).mean())
        if not night.empty
        else 0.0,
        "solar_export_kwh": float(solar["export_kwh"].sum()),
        "solar_export_kwh_per_day": float(solar["export_kwh"].sum() / valid_days),
        "solar_export_average_kw": float(solar["export_kwh"].sum() / solar["interval_h"].sum())
        if not solar.empty
        else 0.0,
        "active_export_average_kw": export_active_average_kw,
        "active_export_hours": export_active_hours,
        "outside_solar_import_kwh": float(outside_solar["import_kwh"].sum()),
        "outside_solar_import_kwh_per_day": float(
            outside_solar["import_kwh"].sum() / valid_days
        ),
        "shiftable_ceiling_kwh": float(daily["shiftable_ceiling_kwh"].sum()),
        "shiftable_ceiling_kwh_per_day": float(
            daily["shiftable_ceiling_kwh"].sum() / valid_days
        ),
        "overlap_days_ratio": float(overlap_days / valid_days),
        "hours_above_kw": hours_above,
        "daily": daily,
        "seasonal": seasons,
        "recurring_windows": recurring_import_windows(data, settings),
    }


def recurring_import_windows(data: pd.DataFrame, settings: AnalysisSettings) -> pd.DataFrame:
    """Détecte des plages de soutirage élevées récurrentes, pas des appareils."""

    if data.empty or data["day"].nunique() < settings.recurring_min_days:
        return pd.DataFrame()
    threshold = max(settings.noise_kw, float(data["import_kw"].quantile(0.90)))
    total_days = data["day"].nunique()
    slot = (
        data.assign(is_high=lambda frame: frame["import_kw"] >= threshold)
        .groupby("minute_of_day", as_index=False)
        .agg(
            mean_kw=("import_kw", "mean"),
            median_kw=("import_kw", "median"),
            high_days=("is_high", "sum"),
        )
        .sort_values("minute_of_day")
    )
    # Une somme de booléens est exacte seulement avec une mesure par jour/pas.
    # Les doublons ont déjà été supprimés ; conserver la règle prudente ci-dessous.
    slot["frequency"] = slot["high_days"] / total_days
    selected = slot[
        (slot["high_days"] >= settings.recurring_min_days)
        & (slot["frequency"] >= settings.recurring_min_ratio)
        & (slot["mean_kw"] >= threshold)
    ].copy()
    if selected.empty:
        return pd.DataFrame()
    nominal_minutes = max(1, round(float(data["interval_h"].median()) * 60))
    selected["block"] = (
        selected["minute_of_day"].diff().fillna(nominal_minutes) != nominal_minutes
    ).cumsum()
    windows = selected.groupby("block", as_index=False).agg(
        start_minute=("minute_of_day", "min"),
        last_minute=("minute_of_day", "max"),
        mean_kw=("mean_kw", "mean"),
        median_kw=("median_kw", "median"),
        frequency=("frequency", "mean"),
    )
    windows["end_minute"] = windows["last_minute"] + nominal_minutes
    windows["duration_h"] = (windows["end_minute"] - windows["start_minute"]) / 60
    windows["Plage"] = windows.apply(
        lambda row: f"{time_label(row.start_minute)} – {time_label(row.end_minute)}",
        axis=1,
    )
    windows["Puissance médiane [kW]"] = windows["median_kw"]
    windows["Fréquence"] = windows["frequency"]
    return windows.sort_values(["frequency", "mean_kw", "duration_h"], ascending=False).head(4)


def seasonal_typical_day(
    data: pd.DataFrame,
    season: str,
    years: Iterable[int] | None = None,
    grouped: bool = False,
) -> pd.DataFrame:
    """Journée type moyenne issue exclusivement des pas réellement mesurés."""

    subset = data[(data["season"] == season) & data["valid_measurement"]].copy()
    if years is not None:
        subset = subset[subset["year"].isin(list(years))]
    if subset.empty:
        return pd.DataFrame()
    groups = ["minute_of_day"] if grouped else ["year", "minute_of_day"]
    profile = (
        subset.groupby(groups, as_index=False)
        .agg(
            import_kw=("import_kw", "mean"),
            export_kw=("export_kw", "mean"),
            measurements=("analysis_timestamp", "size"),
            days=("day", "nunique"),
        )
        .sort_values(groups)
    )
    if grouped:
        profile["year"] = "Moyenne"
    return profile
