"""Tests des règles tarifaires GRD et de la valorisation des quarts d'heure."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from energy_analysis.grd_profiles import export_rates_for_year, profile_for_year
from energy_analysis.ingest import apply_timestamp_convention
from energy_analysis.tariffs import apply_billing_rates, classify_tariff, is_high_tariff


def raw_curve(
    timestamps: list[str],
    *,
    import_kwh: list[float] | None = None,
    export_kwh: list[float] | None = None,
) -> pd.DataFrame:
    """Construit la partie minimale d'une courbe quart-horaire canonique."""

    count = len(timestamps)
    imports = import_kwh or [0.0] * count
    exports = export_kwh or [0.0] * count
    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime(timestamps),
            # Cette puissance volontairement différente démontre que la
            # facturation repose sur les kWh et non directement sur les kW.
            "import_kw": [99.0] * count,
            "export_kw": [77.0] * count,
            "import_kwh": imports,
            "export_kwh": exports,
            "interval_h": [0.25] * count,
            "import_valid": [True] * count,
            "export_valid": [True] * count,
        }
    )


def complete_rates(*, export_energy: dict[int, float | None], export_go: dict[int, float | None]) -> dict[int, dict[str, object]]:
    """Grille simple et complète pour isoler le moteur de facturation."""

    return {
        2026: {
            "energy_ht_ct_kwh": 10.0,
            "energy_bt_ct_kwh": 5.0,
            "distribution_ht_ct_kwh": 4.0,
            "distribution_bt_ct_kwh": 2.0,
            "swissgrid_ht_ct_kwh": 1.0,
            "swissgrid_bt_ct_kwh": 1.0,
            "taxes_ht_ct_kwh": 1.0,
            "taxes_bt_ct_kwh": 1.0,
            "energy_fixed_chf_month": 0.0,
            "distribution_fixed_chf_month": 0.0,
            "swissgrid_fixed_chf_month": 0.0,
            "taxes_fixed_chf_month": 0.0,
            "export_energy_ct_by_quarter": export_energy,
            "export_go_ct_by_quarter": export_go,
        }
    }


def test_groupe_e_high_tariff_boundaries_and_annual_schedule_change() -> None:
    profile_2025 = profile_for_year("Groupe E", 2025)
    assert [
        is_high_tariff(pd.Timestamp(value), profile_2025)
        for value in (
            "2025-01-01 06:59",
            "2025-01-01 07:00",
            "2025-01-01 20:59",
            "2025-01-01 21:00",
        )
    ] == [False, True, True, False]

    profile_2026 = profile_for_year("Groupe E", 2026)
    assert [
        is_high_tariff(pd.Timestamp(value), profile_2026)
        for value in (
            "2026-01-01 06:59",
            "2026-01-01 07:00",
            "2026-01-01 11:59",
            "2026-01-01 12:00",
            "2026-01-01 16:59",
            "2026-01-01 17:00",
            "2026-01-01 22:59",
            "2026-01-01 23:00",
        )
    ] == [False, True, True, False, False, True, True, False]
    # Le profil Groupe E fourni ne force pas le week-end en BT.
    assert is_high_tariff(pd.Timestamp("2026-01-03 18:00"), profile_2026)


def test_romande_energie_high_tariff_is_weekday_only_with_semi_open_bounds() -> None:
    profile = profile_for_year("Romande Energie", 2026)

    assert [
        is_high_tariff(pd.Timestamp(value), profile)
        for value in (
            "2026-01-05 16:59",  # lundi
            "2026-01-05 17:00",
            "2026-01-05 21:59",
            "2026-01-05 22:00",
            "2026-01-03 18:00",  # samedi
        )
    ] == [False, True, True, False, False]


def test_end_of_interval_convention_classifies_the_preceding_quarter_hour() -> None:
    # Les relevés Groupe E indiquent la fin de l'intervalle : la ligne 07:00
    # correspond donc à 06:45–07:00 et reste en BT.
    data = raw_curve(["2026-01-05 07:00", "2026-01-05 07:15"])

    end_classified = classify_tariff(apply_timestamp_convention(data, "end"), "Groupe E")
    start_classified = classify_tariff(apply_timestamp_convention(data, "start"), "Groupe E")

    assert end_classified["analysis_timestamp"].tolist() == [
        pd.Timestamp("2026-01-05 06:45"),
        pd.Timestamp("2026-01-05 07:00"),
    ]
    assert end_classified["tariff_period"].tolist() == ["BT", "HT"]
    assert start_classified["tariff_period"].tolist() == ["HT", "HT"]


def test_billing_uses_measured_kwh_and_separates_import_components_and_go() -> None:
    data = apply_timestamp_convention(
        raw_curve(["2026-02-02 17:00"], import_kwh=[2.5], export_kwh=[1.25]), "start"
    )
    rates = complete_rates(
        export_energy={1: 8.0, 2: 4.0, 3: None, 4: None},
        export_go={1: 2.0, 2: 1.0, 3: None, 4: None},
    )

    energy_only = apply_billing_rates(data, "Romande Energie", rates, include_go=False)
    with_go = apply_billing_rates(data, "Romande Energie", rates, include_go=True)

    row = energy_only.iloc[0]
    assert row["tariff_period"] == "HT"
    assert row["energy_cost_chf"] == pytest.approx(0.25)
    assert row["distribution_cost_chf"] == pytest.approx(0.10)
    assert row["swissgrid_cost_chf"] == pytest.approx(0.025)
    assert row["taxes_cost_chf"] == pytest.approx(0.025)
    assert row["import_variable_cost_chf"] == pytest.approx(0.40)
    assert row["export_energy_revenue_chf"] == pytest.approx(0.10)
    assert row["export_revenue_chf"] == pytest.approx(0.10)
    assert row["net_variable_cost_chf"] == pytest.approx(0.30)
    assert row["import_priced_kwh"] == pytest.approx(2.5)
    assert row["import_unpriced_kwh"] == pytest.approx(0.0)

    assert with_go.loc[0, "export_go_revenue_chf"] == pytest.approx(0.025)
    assert with_go.loc[0, "export_revenue_chf"] == pytest.approx(0.125)
    assert with_go.loc[0, "net_variable_cost_chf"] == pytest.approx(0.275)


def test_export_revenue_uses_civil_quarter_and_keeps_unknown_tariffs_unpriced() -> None:
    data = apply_timestamp_convention(
        raw_curve(
            ["2026-03-31 12:00", "2026-04-01 12:00", "2026-07-01 12:00"],
            export_kwh=[1.0, 1.0, 1.0],
        ),
        "start",
    )
    rates = complete_rates(
        export_energy={1: 10.0, 2: 4.0, 3: None, 4: None},
        export_go={1: 2.0, 2: 1.0, 3: None, 4: None},
    )

    priced = apply_billing_rates(data, "Groupe E", rates)

    assert priced["quarter"].tolist() == [1, 2, 3]
    assert priced["export_energy_rate_ct_kwh"].tolist()[:2] == [10.0, 4.0]
    assert np.isnan(priced.loc[2, "export_energy_rate_ct_kwh"])
    assert priced["export_energy_revenue_chf"].tolist()[:2] == pytest.approx([0.10, 0.04])
    assert np.isnan(priced.loc[2, "export_energy_revenue_chf"])
    assert priced["export_priced_kwh"].tolist() == pytest.approx([1.0, 1.0, 0.0])
    assert priced["export_unpriced_kwh"].tolist() == pytest.approx([0.0, 0.0, 1.0])


def test_groupe_e_profile_exposes_quarterly_reprise_without_zero_filling() -> None:
    export = export_rates_for_year("Groupe E", 2026)

    assert set(export["energy_ct_kwh"]) == {1, 2, 3, 4}
    assert export["energy_ct_kwh"][1] is not None
    assert export["energy_ct_kwh"][2] is not None
    assert export["energy_ct_kwh"][3] is None
    assert export["energy_ct_kwh"][4] is None
