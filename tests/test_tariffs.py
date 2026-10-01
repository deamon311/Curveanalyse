"""Tests des règles tarifaires GRD et de la valorisation des quarts d'heure."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from energy_analysis.grd_profiles import (
    component_rates_for_year,
    export_rates_for_year,
    offers_for_grd,
    profile_for_year,
)
from energy_analysis.ingest import apply_timestamp_convention
from energy_analysis.tariffs import (
    apply_billing_rates,
    classify_tariff,
    default_rate_tables,
    fixed_charges_by_month,
    is_high_tariff,
)


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


def complete_rates(
    *, export_energy: dict[int, float | None], export_go: dict[int, float | None]
) -> dict[int, dict[str, object]]:
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


def test_end_of_interval_is_used_to_classify_the_preceding_quarter_hour() -> None:
    # Les relevés Groupe E indiquent la fin de l'intervalle : la ligne 07:00
    # correspond donc à 06:45–07:00 et reste en BT.
    data = raw_curve(["2026-01-05 07:00", "2026-01-05 07:15"])

    classified = classify_tariff(apply_timestamp_convention(data), "Groupe E")

    assert classified["analysis_timestamp"].tolist() == [
        pd.Timestamp("2026-01-05 06:45"),
        pd.Timestamp("2026-01-05 07:00"),
    ]
    assert classified["tariff_period"].tolist() == ["BT", "HT"]


def test_billing_uses_measured_kwh_and_separates_import_components_and_go() -> None:
    data = apply_timestamp_convention(
        raw_curve(["2026-02-02 17:15"], import_kwh=[2.5], export_kwh=[1.25])
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
    assert np.isnan(row["export_go_revenue_chf"])
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
        )
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


def test_groupe_e_2025_plus_interruptible_invoice_profile_is_preconfigured() -> None:
    """Le profil par défaut reprend la ventilation d'une facture PLUS 2025."""

    offer = next(
        candidate
        for candidate in offers_for_grd("Groupe E")
        if candidate.startswith("PLUS tarif double interruptible")
    )

    profile = component_rates_for_year("Groupe E", 2025, offer)
    rates = profile["rates"]

    assert rates["energy_ht_ct_kwh"] == pytest.approx(16.25)
    assert rates["energy_bt_ct_kwh"] == pytest.approx(11.95)
    assert rates["distribution_ht_ct_kwh"] == pytest.approx(8.27)
    assert rates["distribution_bt_ct_kwh"] == pytest.approx(3.59)
    assert rates["swissgrid_ht_ct_kwh"] == pytest.approx(1.86)
    assert rates["swissgrid_bt_ct_kwh"] == pytest.approx(1.86)
    assert rates["taxes_ht_ct_kwh"] == pytest.approx(2.30)
    assert rates["taxes_bt_ct_kwh"] == pytest.approx(2.30)
    assert rates["distribution_fixed_chf_year"] == pytest.approx(120.0)


def test_groupe_e_2025_fixed_distribution_charge_is_prorated_by_calendar_day() -> None:
    """Les 120 CHF/an sont imputés selon les jours réellement analysés."""

    days = pd.date_range("2025-02-01", periods=17, freq="D")
    data = pd.DataFrame(
        {
            "analysis_timestamp": days,
            "year": days.year,
            "month": days.month,
        }
    )
    rates = {
        2025: {
            "energy_fixed_chf_month": 0.0,
            "distribution_fixed_chf_month": None,
            "swissgrid_fixed_chf_month": 0.0,
            "taxes_fixed_chf_month": 0.0,
            "distribution_fixed_chf_year": 120.0,
        }
    }

    fixed = fixed_charges_by_month(data, rates)

    assert len(fixed) == 1
    assert fixed.loc[0, "days_present"] == 17
    assert fixed.loc[0, "fixed_cost_chf"] == pytest.approx(120.0 * 17 / 365)


def test_fixed_charge_cannot_be_entered_monthly_and_annually_at_the_same_time() -> None:
    """Évite un double comptage lorsqu'une facture est saisie dans deux colonnes."""

    days = pd.date_range("2025-02-01", periods=2, freq="D")
    data = pd.DataFrame(
        {
            "analysis_timestamp": days,
            "year": days.year,
            "month": days.month,
        }
    )
    rates = {
        2025: {
            "energy_fixed_chf_month": 0.0,
            "distribution_fixed_chf_month": 10.0,
            "distribution_fixed_chf_year": 120.0,
            "swissgrid_fixed_chf_month": 0.0,
            "taxes_fixed_chf_month": 0.0,
        }
    }

    fixed = fixed_charges_by_month(data, rates)

    assert fixed.loc[0, "fixed_rate_conflict"]
    assert not fixed.loc[0, "fixed_cost_complete"]
    assert pd.isna(fixed.loc[0, "fixed_cost_chf"])


def test_groupe_e_2025_plus_profile_recomposes_invoice_variable_lines() -> None:
    """Le moteur reproduit les lignes variables du T1 de la facture témoin."""

    offer = next(
        candidate
        for candidate in offers_for_grd("Groupe E")
        if candidate.startswith("PLUS tarif double interruptible")
    )
    component = component_rates_for_year("Groupe E", 2025, offer)
    export = export_rates_for_year("Groupe E", 2025)
    rates = {
        2025: {
            **component["rates"],
            "export_energy_ct_by_quarter": export["energy_ct_kwh"],
            "export_go_ct_by_quarter": export["go_ct_kwh"],
        }
    }
    # Les horodatages bruts donnent la fin du quart d'heure : 07:15 devient
    # 07:00 (HT), tandis que 21:15 devient 21:00 (BT) après normalisation.
    data = apply_timestamp_convention(
        raw_curve(
            ["2025-02-03 07:15", "2025-02-03 21:15"],
            import_kwh=[1467.0, 1555.0],
            export_kwh=[1342.0, 0.0],
        )
    )

    priced = apply_billing_rates(data, "Groupe E", rates, include_go=False)

    assert priced["tariff_period"].tolist() == ["HT", "BT"]
    assert priced["energy_cost_chf"].sum() == pytest.approx(424.21)
    assert priced["distribution_cost_chf"].sum() == pytest.approx(177.1454)
    assert priced["swissgrid_cost_chf"].sum() == pytest.approx(56.2092)
    assert priced["taxes_cost_chf"].sum() == pytest.approx(69.506)
    assert priced["import_variable_cost_chf"].sum() == pytest.approx(727.0706)
    assert priced["export_revenue_chf"].sum() == pytest.approx(139.2996)


def test_groupe_e_2025_invoice_reprise_uses_energy_only_when_go_is_not_selected() -> None:
    """Le choix « sans certificat » n'ajoute pas la GO à la valorisation."""

    export = export_rates_for_year("Groupe E", 2025)

    assert export["energy_ct_kwh"][1] == pytest.approx(10.38)
    assert export["energy_ct_kwh"][2] == pytest.approx(6.0)
    assert export["energy_ct_kwh"][3] == pytest.approx(6.0)
    assert export["energy_ct_kwh"][4] == pytest.approx(9.508)
    data = apply_timestamp_convention(raw_curve(["2025-02-02 12:15"], export_kwh=[1.0]))
    rates = {
        2025: {
            "export_energy_ct_by_quarter": export["energy_ct_kwh"],
            "export_go_ct_by_quarter": export["go_ct_kwh"],
        }
    }

    priced = apply_billing_rates(data, "Groupe E", rates, include_go=False)

    assert priced.loc[0, "export_go_rate_ct_kwh"] == pytest.approx(4.0)
    assert priced.loc[0, "export_energy_revenue_chf"] == pytest.approx(0.1038)
    assert priced.loc[0, "export_revenue_chf"] == pytest.approx(0.1038)


def test_groupe_e_2026_export_total_cap_applies_only_when_requested() -> None:
    """Le plafond contractuel limite énergie + GO à 10.96 ct/kWh en T1 2026."""

    data = apply_timestamp_convention(raw_curve(["2026-02-02 12:15"], export_kwh=[1.0]))
    rates = complete_rates(
        export_energy={1: 10.266, 2: None, 3: None, 4: None},
        export_go={1: 3.0, 2: None, 3: None, 4: None},
    )
    rates[2026]["export_total_cap_ct_by_quarter"] = {1: 10.96}

    uncapped = apply_billing_rates(data, "Groupe E", rates, include_go=True)
    capped = apply_billing_rates(
        data,
        "Groupe E",
        rates,
        include_go=True,
        apply_export_total_cap=True,
    )

    assert uncapped.loc[0, "export_revenue_chf"] == pytest.approx(0.13266)
    assert capped.loc[0, "export_revenue_chf"] == pytest.approx(0.1096)


def test_optional_export_cap_is_blank_for_romande_energie() -> None:
    """La nouvelle colonne de plafond ne doit pas empêcher le profil Romande."""

    _, _, export_rates, _ = default_rate_tables("Romande Energie", [2025])

    assert export_rates["total_cap_ct_kwh"].isna().all()
