"""Calculs de facture estimée à partir des quarts d'heure réseau.

Le module ne reconstitue pas une facture officielle : il applique les montants
choisis par le conseiller aux kWh réellement mesurés, sépare les composantes,
et laisse volontairement ``NaN`` lorsqu'un tarif nécessaire n'est pas connu.
"""

from __future__ import annotations

from calendar import monthrange
from collections.abc import Iterable, Mapping
from typing import Any

import numpy as np
import pandas as pd

from .formatting import MONTH_NAMES
from .grd_profiles import (
    COMPONENTS,
    QUARTERS,
    component_rates_for_year,
    export_rates_for_year,
    profile_for_year,
)

VARIABLE_RATE_COLUMNS = tuple(
    f"{component}_{period}_ct_kwh"
    for component in COMPONENTS
    for period in ("ht", "bt")
)
FIXED_RATE_COLUMNS = tuple(f"{component}_fixed_chf_month" for component in COMPONENTS)


def _optional_float(value: object) -> float | None:
    """Convertit une cellule d'éditeur en float ou en valeur manquante."""

    if value is None or pd.isna(value):
        return None
    return float(value)


def _rate_at(rates: Mapping[int, Mapping[str, Any]], year: int, key: str) -> float | None:
    value = rates.get(int(year), {}).get(key)
    return _optional_float(value)


def _in_period(hour: float, start: float, end: float) -> bool:
    """Test d'une plage semi-ouverte [début, fin), y compris à minuit."""

    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def is_high_tariff(timestamp: pd.Timestamp, profile: Mapping[str, Any]) -> bool:
    """Classe une date locale en HT ou BT avec les bornes [début, fin)."""

    timestamp = pd.Timestamp(timestamp)
    if pd.isna(timestamp):
        return False
    if bool(profile["weekend_low"]) and timestamp.weekday() >= 5:
        return False
    decimal_hour = timestamp.hour + timestamp.minute / 60 + timestamp.second / 3600
    return any(
        _in_period(decimal_hour, float(start), float(end))
        for start, end in profile["high_periods"]
    )


def classify_tariff(data: pd.DataFrame, grd: str) -> pd.DataFrame:
    """Ajoute la période HT/BT et le trimestre civil à chaque pas de mesure.

    L'horodatage d'analyse est utilisé, pas la date brute fournisseur. Ainsi,
    pour un fichier Groupe E dont la date indique la fin d'intervalle, une ligne
    ``07:00`` reste classée dans le quart d'heure 06:45–07:00.
    """

    required = {"analysis_timestamp", "year"}
    missing = required - set(data.columns)
    if missing:
        raise ValueError(f"Colonnes manquantes pour la tarification : {sorted(missing)}")
    result = data.copy()
    timestamps = pd.to_datetime(result["analysis_timestamp"])
    result["tariff_period"] = [
        "HT" if is_high_tariff(timestamp, profile_for_year(grd, int(year))) else "BT"
        for timestamp, year in zip(timestamps, result["year"], strict=True)
    ]
    result["quarter"] = timestamps.dt.quarter.astype("Int64")
    return result


def default_rate_tables(
    grd: str, years: Iterable[int], offer: str | None = None
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list[str]]:
    """Construit les tables éditables des composantes et de la reprise."""

    variable_rows: list[dict[str, object]] = []
    fixed_rows: list[dict[str, object]] = []
    export_rows: list[dict[str, object]] = []
    notes: list[str] = []
    for year in sorted({int(value) for value in years}):
        component = component_rates_for_year(grd, year, offer)
        variable_rows.append({"Année": year, **{
            key: component["rates"][key] for key in VARIABLE_RATE_COLUMNS
        }})
        fixed_rows.append({"Année": year, **{
            key: component["rates"][key] for key in FIXED_RATE_COLUMNS
        }})
        notes.append(f"{year} : {component['note']}")

        export = export_rates_for_year(grd, year)
        for quarter in QUARTERS:
            export_rows.append(
                {
                    "Année": year,
                    "Trimestre": quarter,
                    "energy_ct_kwh": export["energy_ct_kwh"].get(quarter),
                    "go_ct_kwh": export["go_ct_kwh"].get(quarter),
                    "Source": export["source"],
                    "Note": export["note"],
                }
            )
        if export["needs_confirmation"]:
            notes.append(
                f"{year} : la reprise proposée reprend l'année {export['reference_year']} "
                "à confirmer avant calcul."
            )
    return (
        pd.DataFrame(variable_rows),
        pd.DataFrame(fixed_rows),
        pd.DataFrame(export_rows),
        notes,
    )


def rates_from_tables(
    variable_rates: pd.DataFrame,
    fixed_rates: pd.DataFrame,
    export_rates: pd.DataFrame,
) -> dict[int, dict[str, Any]]:
    """Normalise les trois tables éditables pour le moteur de calcul."""

    rates: dict[int, dict[str, Any]] = {}
    for _, row in variable_rates.iterrows():
        year = int(row["Année"])
        rates.setdefault(year, {})
        rates[year].update({key: _optional_float(row.get(key)) for key in VARIABLE_RATE_COLUMNS})
    for _, row in fixed_rates.iterrows():
        year = int(row["Année"])
        rates.setdefault(year, {})
        rates[year].update({key: _optional_float(row.get(key)) for key in FIXED_RATE_COLUMNS})
    for _, row in export_rates.iterrows():
        year = int(row["Année"])
        quarter = int(row["Trimestre"])
        rates.setdefault(year, {})
        rates[year].setdefault("export_energy_ct_by_quarter", {})[quarter] = _optional_float(
            row.get("energy_ct_kwh")
        )
        rates[year].setdefault("export_go_ct_by_quarter", {})[quarter] = _optional_float(
            row.get("go_ct_kwh")
        )
    return rates


def _import_valid(data: pd.DataFrame) -> pd.Series:
    source = data.get("import_valid", data["import_kwh"].notna())
    return source.fillna(False).astype(bool) & data["import_kwh"].notna()


def _export_valid(data: pd.DataFrame) -> pd.Series:
    source = data.get("export_valid", data["export_kwh"].notna())
    return source.fillna(False).astype(bool) & data["export_kwh"].notna()


def _component_rate_series(
    data: pd.DataFrame, rates_by_year: Mapping[int, Mapping[str, Any]], component: str
) -> pd.Series:
    values = []
    for year, period in zip(data["year"], data["tariff_period"], strict=True):
        key = f"{component}_{str(period).lower()}_ct_kwh"
        values.append(_rate_at(rates_by_year, int(year), key))
    return pd.Series(values, index=data.index, dtype="float64")


def _export_rate_series(
    data: pd.DataFrame,
    rates_by_year: Mapping[int, Mapping[str, Any]],
    key: str,
) -> pd.Series:
    values = []
    for year, quarter in zip(data["year"], data["quarter"], strict=True):
        quarter_rates = rates_by_year.get(int(year), {}).get(key, {})
        values.append(_optional_float(quarter_rates.get(int(quarter))))
    return pd.Series(values, index=data.index, dtype="float64")


def apply_billing_rates(
    data: pd.DataFrame,
    grd: str,
    rates_by_year: Mapping[int, Mapping[str, Any]],
    *,
    include_go: bool = False,
) -> pd.DataFrame:
    """Applique les composantes de facture aux énergies mesurées.

    Les coûts import sont calculés exclusivement à partir des kWh importés,
    jamais à partir des kW. Une ligne dont une composante nécessaire est
    absente reste non tarifée plutôt qu'être valorisée arbitrairement à zéro.
    """

    result = classify_tariff(data, grd)
    import_valid = _import_valid(result)
    export_valid = _export_valid(result)
    import_zero = import_valid & result["import_kwh"].eq(0)
    export_zero = export_valid & result["export_kwh"].eq(0)
    result["import_measurement_missing"] = ~import_valid
    result["export_measurement_missing"] = ~export_valid

    component_cost_columns: list[str] = []
    complete_component_rates: list[pd.Series] = []
    for component in COMPONENTS:
        rate_column = f"{component}_rate_ct_kwh"
        cost_column = f"{component}_cost_chf"
        result[rate_column] = _component_rate_series(result, rates_by_year, component)
        result[cost_column] = np.where(
            import_zero,
            0.0,
            np.where(
                import_valid & result[rate_column].notna(),
                result["import_kwh"] * result[rate_column] / 100,
                np.nan,
            ),
        )
        component_cost_columns.append(cost_column)
        complete_component_rates.append(result[rate_column].notna())

    component_rates_complete = pd.concat(complete_component_rates, axis=1).all(axis=1) | import_zero
    result["import_rate_complete"] = component_rates_complete
    result["import_variable_cost_chf"] = result[component_cost_columns].sum(
        axis=1, min_count=len(component_cost_columns)
    )
    result["import_priced_kwh"] = np.where(
        import_valid & component_rates_complete, result["import_kwh"], 0.0
    )
    result["import_unpriced_kwh"] = np.where(
        import_valid & ~component_rates_complete, result["import_kwh"], 0.0
    )

    result["export_energy_rate_ct_kwh"] = _export_rate_series(
        result, rates_by_year, "export_energy_ct_by_quarter"
    )
    result["export_go_rate_ct_kwh"] = _export_rate_series(
        result, rates_by_year, "export_go_ct_by_quarter"
    )
    result["export_energy_revenue_chf"] = np.where(
        export_zero,
        0.0,
        np.where(
            export_valid & result["export_energy_rate_ct_kwh"].notna(),
            result["export_kwh"] * result["export_energy_rate_ct_kwh"] / 100,
            np.nan,
        ),
    )
    result["export_go_revenue_chf"] = np.where(
        export_zero,
        0.0,
        np.where(
            export_valid & result["export_go_rate_ct_kwh"].notna(),
            result["export_kwh"] * result["export_go_rate_ct_kwh"] / 100,
            np.nan,
        ),
    )
    expected_export_rates = result["export_energy_rate_ct_kwh"].notna() | export_zero
    if include_go:
        expected_export_rates &= result["export_go_rate_ct_kwh"].notna() | export_zero
        result["export_revenue_chf"] = result[
            ["export_energy_revenue_chf", "export_go_revenue_chf"]
        ].sum(axis=1, min_count=2)
    else:
        result["export_revenue_chf"] = result["export_energy_revenue_chf"]
    result["export_rate_complete"] = expected_export_rates
    result["export_priced_kwh"] = np.where(
        export_valid & expected_export_rates, result["export_kwh"], 0.0
    )
    result["export_unpriced_kwh"] = np.where(
        export_valid & ~expected_export_rates, result["export_kwh"], 0.0
    )
    result["net_variable_cost_chf"] = result["import_variable_cost_chf"] - result[
        "export_revenue_chf"
    ]
    return result


def fixed_charges_by_month(
    data: pd.DataFrame, rates_by_year: Mapping[int, Mapping[str, Any]]
) -> pd.DataFrame:
    """Estime les frais fixes mensuels au prorata des jours analysés.

    Le prorata se base sur les jours calendaires présents dans la courbe, pas
    sur un remplissage artificiel des trous de mesure.
    """

    if data.empty:
        return pd.DataFrame()
    calendar = data.copy()
    calendar["calendar_day"] = calendar["analysis_timestamp"].dt.normalize()
    rows: list[dict[str, object]] = []
    for (year, month), group in calendar.groupby(["year", "month"], sort=True):
        days_present = int(group["calendar_day"].nunique())
        days_in_month = monthrange(int(year), int(month))[1]
        prorata = days_present / days_in_month
        row: dict[str, object] = {
            "year": int(year),
            "month": int(month),
            "days_present": days_present,
            "days_in_month": days_in_month,
            "prorata": prorata,
        }
        cost_columns = []
        known_rates = []
        for component in COMPONENTS:
            rate_key = f"{component}_fixed_chf_month"
            cost_key = f"{component}_fixed_cost_chf"
            rate = _rate_at(rates_by_year, int(year), rate_key)
            row[rate_key] = rate
            row[cost_key] = np.nan if rate is None else rate * prorata
            cost_columns.append(cost_key)
            known_rates.append(rate is not None)
        row["fixed_cost_complete"] = all(known_rates)
        row["fixed_cost_chf"] = pd.DataFrame([row])[cost_columns].sum(
            axis=1, min_count=len(cost_columns)
        ).iloc[0]
        rows.append(row)
    return pd.DataFrame(rows)


def _sum_or_nan(values: pd.Series) -> float:
    value = values.sum(min_count=1)
    return float(value) if pd.notna(value) else float("nan")


def billing_summary(priced: pd.DataFrame, fixed: pd.DataFrame) -> pd.DataFrame:
    """Synthèse par année, avec la couverture des postes effectivement tarifés."""

    if priced.empty:
        return pd.DataFrame()
    rows: list[dict[str, object]] = []
    for year, group in priced.groupby("year", sort=True):
        ht = group[group["tariff_period"] == "HT"]
        bt = group[group["tariff_period"] == "BT"]
        row: dict[str, object] = {
            "year": int(year),
            "import_ht_kwh": _sum_or_nan(ht["import_kwh"]),
            "import_bt_kwh": _sum_or_nan(bt["import_kwh"]),
            "import_priced_kwh": _sum_or_nan(group["import_priced_kwh"]),
            "import_unpriced_kwh": _sum_or_nan(group["import_unpriced_kwh"]),
            "export_kwh": _sum_or_nan(group["export_kwh"]),
            "export_priced_kwh": _sum_or_nan(group["export_priced_kwh"]),
            "export_unpriced_kwh": _sum_or_nan(group["export_unpriced_kwh"]),
            "import_missing_intervals": int(group["import_measurement_missing"].sum()),
            "export_missing_intervals": int(group["export_measurement_missing"].sum()),
        }
        for component in COMPONENTS:
            row[f"{component}_cost_chf"] = _sum_or_nan(group[f"{component}_cost_chf"])
        row["import_variable_cost_chf"] = _sum_or_nan(group["import_variable_cost_chf"])
        row["export_energy_revenue_chf"] = _sum_or_nan(group["export_energy_revenue_chf"])
        row["export_go_revenue_chf"] = _sum_or_nan(group["export_go_revenue_chf"])
        row["export_revenue_chf"] = _sum_or_nan(group["export_revenue_chf"])
        rows.append(row)
    summary = pd.DataFrame(rows)
    if fixed.empty:
        summary["fixed_cost_chf"] = np.nan
        summary["fixed_complete"] = False
    else:
        fixed_summary = (
            fixed.groupby("year", as_index=False)
            .agg(
                fixed_cost_chf=("fixed_cost_chf", _sum_or_nan),
                fixed_complete=("fixed_cost_complete", "all"),
                fixed_prorata=("prorata", "sum"),
            )
            .astype({"year": int})
        )
        summary = summary.merge(fixed_summary, on="year", how="left")
        summary["fixed_complete"] = summary["fixed_complete"].fillna(False)
    summary["is_complete"] = (
        (summary["import_unpriced_kwh"].fillna(0) <= 1e-9)
        & (summary["export_unpriced_kwh"].fillna(0) <= 1e-9)
        & (summary["import_missing_intervals"] == 0)
        & (summary["export_missing_intervals"] == 0)
        & summary["fixed_complete"]
    )
    summary["net_estimated_cost_chf"] = np.where(
        summary["is_complete"],
        summary["import_variable_cost_chf"]
        - summary["export_revenue_chf"]
        + summary["fixed_cost_chf"],
        np.nan,
    )
    return summary


def monthly_billing_summary(priced: pd.DataFrame, fixed: pd.DataFrame) -> pd.DataFrame:
    """Synthèse mensuelle utilisée par le tableau et le graphique tarifaires."""

    if priced.empty:
        return pd.DataFrame()
    rows: list[dict[str, object]] = []
    for (year, month), group in priced.groupby(["year", "month"], sort=True):
        row: dict[str, object] = {
            "year": int(year),
            "month": int(month),
            "label": f"{MONTH_NAMES[int(month)][:3]} {int(year)}",
            "import_ht_kwh": _sum_or_nan(group.loc[group["tariff_period"] == "HT", "import_kwh"]),
            "import_bt_kwh": _sum_or_nan(group.loc[group["tariff_period"] == "BT", "import_kwh"]),
            "import_priced_kwh": _sum_or_nan(group["import_priced_kwh"]),
            "import_unpriced_kwh": _sum_or_nan(group["import_unpriced_kwh"]),
            "export_priced_kwh": _sum_or_nan(group["export_priced_kwh"]),
            "export_unpriced_kwh": _sum_or_nan(group["export_unpriced_kwh"]),
            "import_missing_intervals": int(group["import_measurement_missing"].sum()),
            "export_missing_intervals": int(group["export_measurement_missing"].sum()),
            "import_variable_cost_chf": _sum_or_nan(group["import_variable_cost_chf"]),
            "export_revenue_chf": _sum_or_nan(group["export_revenue_chf"]),
        }
        for component in COMPONENTS:
            row[f"{component}_cost_chf"] = _sum_or_nan(group[f"{component}_cost_chf"])
        rows.append(row)
    summary = pd.DataFrame(rows)
    if fixed.empty:
        summary["fixed_cost_chf"] = np.nan
        summary["fixed_complete"] = False
    else:
        values = fixed[["year", "month", "fixed_cost_chf", "fixed_cost_complete"]]
        summary = summary.merge(values, on=["year", "month"], how="left")
        summary["fixed_complete"] = summary["fixed_cost_complete"].fillna(False)
        summary = summary.drop(columns="fixed_cost_complete")
    summary["is_complete"] = (
        (summary["import_unpriced_kwh"].fillna(0) <= 1e-9)
        & (summary["export_unpriced_kwh"].fillna(0) <= 1e-9)
        & (summary["import_missing_intervals"] == 0)
        & (summary["export_missing_intervals"] == 0)
        & summary["fixed_complete"]
    )
    summary["net_estimated_cost_chf"] = np.where(
        summary["is_complete"],
        summary["import_variable_cost_chf"]
        - summary["export_revenue_chf"]
        + summary["fixed_cost_chf"],
        np.nan,
    )
    return summary


def quarterly_export_summary(priced: pd.DataFrame) -> pd.DataFrame:
    """Détaille les kWh injectés et leur valorisation trimestre par trimestre."""

    if priced.empty:
        return pd.DataFrame()
    rows: list[dict[str, object]] = []
    for (year, quarter), group in priced.groupby(["year", "quarter"], sort=True):
        energy_rates = group["export_energy_rate_ct_kwh"].dropna().unique()
        go_rates = group["export_go_rate_ct_kwh"].dropna().unique()
        rows.append(
            {
                "year": int(year),
                "quarter": int(quarter),
                "label": f"T{int(quarter)} {int(year)}",
                "export_kwh": _sum_or_nan(group["export_kwh"]),
                "export_priced_kwh": _sum_or_nan(group["export_priced_kwh"]),
                "export_unpriced_kwh": _sum_or_nan(group["export_unpriced_kwh"]),
                "energy_rate_ct_kwh": float(energy_rates[0]) if len(energy_rates) == 1 else np.nan,
                "go_rate_ct_kwh": float(go_rates[0]) if len(go_rates) == 1 else np.nan,
                "energy_revenue_chf": _sum_or_nan(group["export_energy_revenue_chf"]),
                "go_revenue_chf": _sum_or_nan(group["export_go_revenue_chf"]),
                "export_revenue_chf": _sum_or_nan(group["export_revenue_chf"]),
            }
        )
    return pd.DataFrame(rows)
