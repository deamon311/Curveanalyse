"""Analyse énergétique Soleol — Streamlit.

Les calculs sont volontairement séparés dans energy_analysis/ afin de pouvoir
les tester sans l'interface. Cette application ne déduit jamais la consommation
totale du bâtiment ni la production PV totale à partir des seuls flux réseau.
"""

from __future__ import annotations

import io

import pandas as pd
import streamlit as st

from energy_analysis.charts import (
    annual_energy_chart,
    billing_components_chart,
    comparable_energy_chart,
    monthly_billing_chart,
    monthly_energy_chart,
    seasonal_energy_chart,
    threshold_hours_chart,
    typical_day_chart,
)
from energy_analysis.config import BRAND_ORANGE, SEASON_ORDER, AnalysisSettings
from energy_analysis.formatting import chf, hours, kw, kwh, pct, swiss_number
from energy_analysis.grd_profiles import GRD_NAMES, offers_for_grd, profile_for_year
from energy_analysis.ingest import (
    apply_timestamp_convention,
    combine_imports,
    read_energy_file,
)
from energy_analysis.metrics import (
    add_analysis_flags,
    annual_summary,
    comparable_years,
    monthly_summary,
    profile_metrics,
    seasonal_typical_day,
)
from energy_analysis.models import ImportedFile
from energy_analysis.recommendations import build_recommendations, client_summary
from energy_analysis.tariffs import (
    apply_billing_rates,
    billing_summary,
    default_rate_tables,
    fixed_charges_by_month,
    monthly_billing_summary,
    quarterly_export_summary,
    rates_from_tables,
)

st.set_page_config(
    page_title="Analyse énergétique | Soleol",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)


def inject_style() -> None:
    st.markdown(
        f"""
        <style>
            :root {{
                --soleol: {BRAND_ORANGE};
                --surface: #181B1F;
                --panel: #20242A;
                --text: #F4F4F4;
                --muted: #B7B7B7;
            }}
            .stApp {{
                background: #111315;
                color: var(--text);
            }}
            [data-testid="stSidebar"] {{
                background: #171A1E;
                border-right: 1px solid #2E343A;
            }}
            [data-testid="stSidebar"] * {{
                color: var(--text);
            }}
            .soleol-hero {{
                background: linear-gradient(110deg, #171A1E 0%, #1F242A 62%, #55251D 100%);
                border: 1px solid #343A40;
                border-left: 6px solid var(--soleol);
                border-radius: 14px;
                padding: 1.15rem 1.35rem;
                margin: 0 0 1.15rem 0;
            }}
            .soleol-brand {{
                font-weight: 800;
                font-size: 1.55rem;
                letter-spacing: .08em;
                color: #FFFFFF;
            }}
            .soleol-kicker {{
                color: #F29B83;
                font-size: .77rem;
                font-weight: 700;
                letter-spacing: .12em;
                text-transform: uppercase;
            }}
            .soleol-title {{
                color: #FFFFFF;
                font-size: 1.35rem;
                font-weight: 650;
                margin-top: .2rem;
            }}
            .soleol-subtitle {{
                color: var(--muted);
                margin-top: .25rem;
            }}
            .advice-card {{
                background: #1A1E23;
                border: 1px solid #343A40;
                border-left: 4px solid var(--soleol);
                border-radius: 10px;
                padding: .95rem 1.05rem;
                margin: .55rem 0;
            }}
            .advice-category {{
                color: #F29B83;
                font-size: .74rem;
                text-transform: uppercase;
                font-weight: 750;
                letter-spacing: .08em;
            }}
            .advice-title {{
                color: #FFFFFF;
                font-size: 1.04rem;
                font-weight: 700;
                margin: .18rem 0 .42rem;
            }}
            div[data-testid="stMetric"] {{
                background: #1A1E23;
                border: 1px solid #30363D;
                border-radius: 10px;
                padding: .75rem .9rem;
            }}
            div[data-testid="stMetricLabel"] {{
                color: #B7B7B7;
            }}
            div[data-testid="stMetricValue"] {{
                color: #FFFFFF;
            }}
            .client-summary {{
                background: rgba(224, 85, 58, .10);
                border: 1px solid rgba(224, 85, 58, .42);
                border-radius: 10px;
                padding: 1rem 1.1rem;
                color: #F4F4F4;
                margin-bottom: .8rem;
            }}
            [data-testid="stDownloadButton"] button,
            .stButton button {{
                border-color: #E0553A !important;
                color: #FFFFFF !important;
            }}
        </style>
        """,
        unsafe_allow_html=True,
    )


@st.cache_data(show_spinner=False)
def parse_uploaded_file(file_name: str, contents: bytes) -> ImportedFile:
    """Cache la lecture d'un fichier inchangé pendant les interactions UI."""

    buffer = io.BytesIO(contents)
    buffer.name = file_name
    return read_energy_file(buffer)


def energy_sum(data: pd.DataFrame, column: str) -> float:
    value = data[column].sum(min_count=1)
    return float(value) if pd.notna(value) else 0.0


def metric_with_caption(label: str, value: str, caption: str = "") -> None:
    st.metric(label, value)
    if caption:
        st.caption(caption)


def dataframe_with_number_format(frame: pd.DataFrame, formats: dict[str, str]) -> None:
    st.dataframe(
        frame.style.format(formats, na_rep="—"),
        width="stretch",
        hide_index=True,
    )


def client_metadata(imported: list[ImportedFile]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in imported:
        for key, value in item.metadata.items():
            result.setdefault(key, value)
    return result


def show_header(metadata: dict[str, str], data: pd.DataFrame) -> None:
    period = (
        f"{data['analysis_timestamp'].min():%d.%m.%Y} – "
        f"{data['analysis_timestamp'].max():%d.%m.%Y}"
    )
    details = [value for value in (metadata.get("Adresse"), metadata.get("Objet")) if value]
    subtitle = " · ".join(details) if details else "Courbes de charge réseau importées"
    st.markdown(
        f"""
        <div class="soleol-hero">
            <div class="soleol-kicker">Conseil énergétique photovoltaïque</div>
            <div class="soleol-brand">SOLEOL</div>
            <div class="soleol-title">Analyse de courbes de charge et tarifs GRD</div>
            <div class="soleol-subtitle">{subtitle} · Période analysée : {period}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


VARIABLE_RATE_LABELS = {
    "energy_ht_ct_kwh": "Énergie HT [ct/kWh]",
    "energy_bt_ct_kwh": "Énergie BT [ct/kWh]",
    "distribution_ht_ct_kwh": "Distribution HT [ct/kWh]",
    "distribution_bt_ct_kwh": "Distribution BT [ct/kWh]",
    "swissgrid_ht_ct_kwh": "Swissgrid HT [ct/kWh]",
    "swissgrid_bt_ct_kwh": "Swissgrid BT [ct/kWh]",
    "taxes_ht_ct_kwh": "Taxes HT [ct/kWh]",
    "taxes_bt_ct_kwh": "Taxes BT [ct/kWh]",
}
FIXED_RATE_LABELS = {
    "energy_fixed_chf_month": "Énergie [CHF/mois]",
    "distribution_fixed_chf_month": "Distribution & mesure [CHF/mois]",
    "swissgrid_fixed_chf_month": "Swissgrid [CHF/mois]",
    "taxes_fixed_chf_month": "Taxes [CHF/mois]",
}


def tariff_table_key(grd: str, offer: str, years: list[int], table: str) -> str:
    years_key = "_".join(str(year) for year in years)
    return f"tariff_{table}_{grd}_{offer}_{years_key}"


def show_tariff_configuration(
    grd: str, offer: str, years: list[int]
) -> tuple[dict[int, dict[str, object]], bool, pd.DataFrame]:
    """Affiche et lit les montants servant à l'estimation tarifaire."""

    st.subheader("Tarif GRD et paramètres de facture")
    st.caption(
        "Cette première version cible le tarif double basse tension. Les montants sont "
        "appliqués aux kWh mesurés ; ils restent modifiables et ne remplacent pas une facture."
    )
    schedules = []
    for year in years:
        schedule = profile_for_year(grd, year)
        schedules.append(
            {
                "Année": year,
                "Horaires appliqués": schedule["label"],
                "Statut": (
                    "À confirmer — calendrier repris d’une autre année"
                    if schedule["schedule_needs_confirmation"]
                    else "Calendrier intégré — tarif double"
                ),
            }
        )
    st.dataframe(pd.DataFrame(schedules), width="stretch", hide_index=True)
    if any(profile_for_year(grd, year)["schedule_needs_confirmation"] for year in years):
        st.warning(
            "Au moins une année ne dispose pas encore d’un calendrier officiel dans l’application. "
            "Le dernier calendrier connu est proposé uniquement comme repère."
        )

    variable_defaults, fixed_defaults, export_defaults, notes = default_rate_tables(
        grd, years, offer
    )
    if grd == "Groupe E":
        st.info(
            "Les horaires Groupe E sont intégrés. Les prix du fichier fourni sont globaux et "
            "non ventilés : renseignez les quatre composantes de la facture client avant de "
            "lire une estimation de coût complète."
        )
    else:
        st.info(
            "Les préremplissages Romande Energie correspondent au tarif Double, offre "
            "Energie Suisse/Romande, hors TVA et hors taxes cantonales ou communales."
        )
    for note in notes:
        st.caption(note)

    variable_config = {
        "Année": st.column_config.NumberColumn("Année", format="%d"),
        **{
            column: st.column_config.NumberColumn(label, min_value=0.0, step=0.001)
            for column, label in VARIABLE_RATE_LABELS.items()
        },
    }
    fixed_config = {
        "Année": st.column_config.NumberColumn("Année", format="%d"),
        **{
            column: st.column_config.NumberColumn(label, min_value=0.0, step=0.01)
            for column, label in FIXED_RATE_LABELS.items()
        },
    }
    export_config = {
        "Année": st.column_config.NumberColumn("Année", format="%d"),
        "Trimestre": st.column_config.NumberColumn("Trimestre", format="T%d"),
        "energy_ct_kwh": st.column_config.NumberColumn(
            "Reprise énergie [ct/kWh]", min_value=0.0, step=0.001
        ),
        "go_ct_kwh": st.column_config.NumberColumn("GO [ct/kWh]", min_value=0.0, step=0.001),
        "Source": st.column_config.TextColumn("Source", width="medium"),
        "Note": st.column_config.TextColumn("Note", width="large"),
    }

    st.markdown("#### Montants variables hors TVA")
    variable_rates = st.data_editor(
        variable_defaults,
        column_config=variable_config,
        disabled=["Année"],
        hide_index=True,
        num_rows="fixed",
        width="stretch",
        key=tariff_table_key(grd, offer, years, "variable"),
    )
    st.markdown("#### Frais fixes hors TVA")
    st.caption(
        "Les frais fixes sont indiqués en CHF/mois et proratisés selon les jours calendaires "
        "présents dans la période analysée. Mettre 0 lorsqu’aucun frais ne s’applique."
    )
    fixed_rates = st.data_editor(
        fixed_defaults,
        column_config=fixed_config,
        disabled=["Année"],
        hide_index=True,
        num_rows="fixed",
        width="stretch",
        key=tariff_table_key(grd, offer, years, "fixed"),
    )
    st.markdown("#### Reprise photovoltaïque par trimestre")
    include_go = st.checkbox(
        "Inclure la rémunération des garanties d’origine (GO)",
        value=False,
        help="À activer uniquement si le client a effectivement cédé ses garanties d’origine au GRD.",
        key=tariff_table_key(grd, offer, years, "go"),
    )
    st.caption(
        "Les cellules vides signifient « tarif non publié ou non confirmé », jamais 0 ct/kWh. "
        "Les valeurs de reprise doivent être vérifiées sur la facture ou le contrat client."
    )
    export_rates = st.data_editor(
        export_defaults,
        column_config=export_config,
        disabled=["Année", "Trimestre", "Source", "Note"],
        hide_index=True,
        num_rows="fixed",
        width="stretch",
        key=tariff_table_key(grd, offer, years, "export"),
    )
    return rates_from_tables(variable_rates, fixed_rates, export_rates), include_go, export_rates


def show_empty_state() -> None:
    st.markdown(
        """
        <div class="soleol-hero">
            <div class="soleol-kicker">Conseil énergétique photovoltaïque</div>
            <div class="soleol-brand">SOLEOL</div>
            <div class="soleol-title">Analyse de courbes de charge</div>
            <div class="soleol-subtitle">Import, injection et potentiel de pilotage à partir de mesures réelles.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.info(
        "Ajoutez une ou plusieurs courbes Excel dans le panneau de gauche. "
        "Les fichiers restent utilisés uniquement pour la session d’analyse."
    )
    left, middle, right = st.columns(3)
    with left:
        st.markdown("### 1. Charger")
        st.write(
            "Déposez les années disponibles. Les mêmes horodatages ne sont jamais comptés deux fois."
        )
    with middle:
        st.markdown("### 2. Lire le profil")
        st.write(
            "Comparez les années, les mois et les quatre journées types construites sur les mesures réelles."
        )
    with right:
        st.markdown("### 3. Conseiller")
        st.write("Priorisez le pilotage des usages avant toute étude de batterie.")


def show_summary_tab(
    data: pd.DataFrame,
    all_data: pd.DataFrame,
    annual: pd.DataFrame,
    monthly: pd.DataFrame,
    selected_years: list[int],
) -> None:
    total_import = energy_sum(data, "import_kwh")
    total_export = energy_sum(data, "export_kwh")
    peak_import = float(data["import_kw"].max())
    peak_export = float(data["export_kw"].max())
    valid_coverage = float(data["valid_measurement"].mean())
    peak_import_time = data.loc[data["import_kw"].idxmax(), "timestamp"]
    peak_export_time = data.loc[data["export_kw"].idxmax(), "timestamp"]

    st.subheader("Synthèse énergétique")
    st.caption(
        "Le solde import − injection est un indicateur de flux réseau. "
        "Il ne représente ni la consommation totale du bâtiment ni la production PV totale."
    )
    columns = st.columns(6)
    with columns[0]:
        metric_with_caption("Import réseau", kwh(total_import))
    with columns[1]:
        metric_with_caption("Export / injection", kwh(total_export))
    with columns[2]:
        metric_with_caption("Solde réseau", kwh(total_import - total_export))
    with columns[3]:
        metric_with_caption(
            "Pic soutirage", kw(peak_import), f"Source : {peak_import_time:%d.%m.%Y %H:%M}"
        )
    with columns[4]:
        metric_with_caption(
            "Pic injection", kw(peak_export), f"Source : {peak_export_time:%d.%m.%Y %H:%M}"
        )
    with columns[5]:
        metric_with_caption(
            "Mesures exploitables", pct(valid_coverage * 100), "Import et injection connus"
        )

    st.plotly_chart(annual_energy_chart(annual), width="stretch")
    annual_display = annual[
        [
            "year",
            "import_kwh",
            "export_kwh",
            "balance_kwh",
            "peak_import_kw",
            "peak_export_kw",
            "coverage",
            "period_status",
        ]
    ].rename(
        columns={
            "year": "Année",
            "import_kwh": "Import [kWh]",
            "export_kwh": "Injection [kWh]",
            "balance_kwh": "Solde réseau [kWh]",
            "peak_import_kw": "Pic import [kW]",
            "peak_export_kw": "Pic injection [kW]",
            "coverage": "Couverture",
            "period_status": "Période",
        }
    )
    dataframe_with_number_format(
        annual_display,
        {
            "Import [kWh]": "{:,.0f}",
            "Injection [kWh]": "{:,.0f}",
            "Solde réseau [kWh]": "{:,.0f}",
            "Pic import [kW]": "{:,.2f}",
            "Pic injection [kW]": "{:,.2f}",
            "Couverture": "{:.1%}",
        },
    )

    current_year = max(selected_years)
    previous_year = current_year - 1
    comparison, info = comparable_years(all_data, current_year, previous_year)
    st.divider()
    st.subheader(f"Comparaison {current_year} / {previous_year}")
    if comparison.empty or info is None:
        st.info(
            "La comparaison N / N-1 s’affichera lorsque les deux années seront présentes "
            "dans les fichiers chargés."
        )
    else:
        previous = comparison.loc[comparison["year"] == previous_year].iloc[0]
        current = comparison.loc[comparison["year"] == current_year].iloc[0]
        import_change = (
            (current["import_kwh"] / previous["import_kwh"] - 1) * 100
            if previous["import_kwh"]
            else 0.0
        )
        export_change = (
            (current["export_kwh"] / previous["export_kwh"] - 1) * 100
            if previous["export_kwh"]
            else 0.0
        )
        st.caption(
            f"Mêmes pas valides : {info['first']:%d.%m.%Y} – {info['last']:%d.%m.%Y} "
            f"({swiss_number(info['measurements'])} quarts d’heure strictement communs)."
        )
        first, second, third = st.columns(3)
        with first:
            metric_with_caption(
                "Évolution import",
                pct(import_change, sign=True),
                f"{kwh(previous['import_kwh'])} → {kwh(current['import_kwh'])}",
            )
        with second:
            metric_with_caption(
                "Évolution injection",
                pct(export_change, sign=True),
                f"{kwh(previous['export_kwh'])} → {kwh(current['export_kwh'])}",
            )
        with third:
            metric_with_caption(
                "Évolution solde réseau",
                kwh(current["balance_kwh"] - previous["balance_kwh"]),
                "Valeur positive : solde import − injection en hausse",
            )
        st.plotly_chart(comparable_energy_chart(comparison), width="stretch")
        st.info(
            "Cette évolution décrit les flux observés. Les mesures réseau seules ne permettent "
            "pas d’en attribuer la cause à un équipement, à la météo ou à l’occupation."
        )

    st.divider()
    st.subheader("Résumé mensuel")
    st.plotly_chart(monthly_energy_chart(monthly), width="stretch")
    monthly_display = monthly[
        [
            "label",
            "import_kwh",
            "export_kwh",
            "balance_kwh",
            "peak_import_kw",
            "peak_export_kw",
            "coverage",
        ]
    ].rename(
        columns={
            "label": "Mois",
            "import_kwh": "Import [kWh]",
            "export_kwh": "Injection [kWh]",
            "balance_kwh": "Solde réseau [kWh]",
            "peak_import_kw": "Pic import [kW]",
            "peak_export_kw": "Pic injection [kW]",
            "coverage": "Couverture",
        }
    )
    dataframe_with_number_format(
        monthly_display,
        {
            "Import [kWh]": "{:,.0f}",
            "Injection [kWh]": "{:,.0f}",
            "Solde réseau [kWh]": "{:,.0f}",
            "Pic import [kW]": "{:,.2f}",
            "Pic injection [kW]": "{:,.2f}",
            "Couverture": "{:.1%}",
        },
    )


def tariff_sum(summary: pd.DataFrame, column: str) -> float | None:
    value = summary[column].sum(min_count=1)
    return float(value) if pd.notna(value) else None


def show_tariff_results(
    priced: pd.DataFrame,
    annual_billing: pd.DataFrame,
    monthly_billing: pd.DataFrame,
    quarterly_billing: pd.DataFrame,
    grd: str,
    include_go: bool,
) -> None:
    """Affiche la lecture client de l'estimation tarifaire paramétrée."""

    st.divider()
    st.subheader("Estimation de facture sur les flux réseau mesurés")
    st.caption(
        "Montants hors TVA, hors éventuelle composante puissance et hors postes non renseignés. "
        "La reprise PV est une recette distincte ; elle ne comprend ni réseau ni taxes."
    )
    if annual_billing.empty:
        st.info("Aucune mesure tarifable n’est disponible.")
        return

    import_total = energy_sum(priced, "import_kwh")
    export_total = energy_sum(priced, "export_kwh")
    import_priced = energy_sum(priced, "import_priced_kwh")
    export_priced = energy_sum(priced, "export_priced_kwh")
    import_cost = tariff_sum(annual_billing, "import_variable_cost_chf")
    export_revenue = tariff_sum(annual_billing, "export_revenue_chf")
    fixed_cost = tariff_sum(annual_billing, "fixed_cost_chf")
    net_cost = tariff_sum(annual_billing, "net_estimated_cost_chf")
    complete = bool(annual_billing["is_complete"].all())

    first, second, third, fourth = st.columns(4)
    with first:
        metric_with_caption(
            "Coût variable import",
            chf(import_cost, 0),
            f"{kwh(import_priced)} tarifés sur {kwh(import_total)}",
        )
    with second:
        metric_with_caption(
            "Reprise PV",
            chf(export_revenue, 0),
            f"{kwh(export_priced)} tarifés sur {kwh(export_total)}"
            + (" · GO incluse" if include_go else " · hors GO"),
        )
    with third:
        metric_with_caption(
            "Frais fixes estimés",
            chf(fixed_cost, 0),
            "Prorata des jours calendaires analysés",
        )
    with fourth:
        metric_with_caption(
            "Solde estimé",
            chf(net_cost, 0) if complete else "À compléter",
            "Coût import − reprise PV + frais fixes",
        )

    unpriced_import = energy_sum(priced, "import_unpriced_kwh")
    unpriced_export = energy_sum(priced, "export_unpriced_kwh")
    if not complete:
        messages = []
        if unpriced_import > 0.01:
            messages.append(f"{kwh(unpriced_import)} d’import sans les quatre tarifs variables")
        if unpriced_export > 0.01:
            messages.append(f"{kwh(unpriced_export)} d’injection sans reprise confirmée")
        missing_import = int(annual_billing["import_missing_intervals"].sum())
        missing_export = int(annual_billing["export_missing_intervals"].sum())
        if missing_import or missing_export:
            messages.append(
                f"{swiss_number(missing_import + missing_export)} pas de mesure incomplet(s)"
            )
        if not bool(annual_billing["fixed_complete"].all()):
            messages.append("au moins un frais fixe mensuel non renseigné")
        st.warning(
            "Le solde complet n’est pas affiché : "
            + ("; ".join(messages) if messages else "un paramètre reste incomplet")
            + ". Complétez les cellules manquantes plutôt que d’interpréter un zéro."
        )
    else:
        st.success(
            "Tous les postes saisis couvrent la période analysée. Vérifiez néanmoins le produit, "
            "les taxes locales et la TVA avec la facture client."
        )

    st.plotly_chart(billing_components_chart(annual_billing), width="stretch")
    annual_display = annual_billing[
        [
            "year",
            "import_ht_kwh",
            "import_bt_kwh",
            "energy_cost_chf",
            "distribution_cost_chf",
            "swissgrid_cost_chf",
            "taxes_cost_chf",
            "fixed_cost_chf",
            "export_revenue_chf",
            "net_estimated_cost_chf",
            "is_complete",
        ]
    ].rename(
        columns={
            "year": "Année",
            "import_ht_kwh": "Import HT [kWh]",
            "import_bt_kwh": "Import BT [kWh]",
            "energy_cost_chf": "Énergie [CHF]",
            "distribution_cost_chf": "Distribution [CHF]",
            "swissgrid_cost_chf": "Swissgrid [CHF]",
            "taxes_cost_chf": "Taxes [CHF]",
            "fixed_cost_chf": "Frais fixes [CHF]",
            "export_revenue_chf": "Reprise PV [CHF]",
            "net_estimated_cost_chf": "Solde estimé [CHF]",
            "is_complete": "Complet",
        }
    )
    dataframe_with_number_format(
        annual_display,
        {
            "Import HT [kWh]": "{:,.0f}",
            "Import BT [kWh]": "{:,.0f}",
            "Énergie [CHF]": "{:,.2f}",
            "Distribution [CHF]": "{:,.2f}",
            "Swissgrid [CHF]": "{:,.2f}",
            "Taxes [CHF]": "{:,.2f}",
            "Frais fixes [CHF]": "{:,.2f}",
            "Reprise PV [CHF]": "{:,.2f}",
            "Solde estimé [CHF]": "{:,.2f}",
        },
    )

    st.subheader("Lecture mensuelle")
    st.plotly_chart(monthly_billing_chart(monthly_billing), width="stretch")
    monthly_display = monthly_billing[
        [
            "label",
            "import_ht_kwh",
            "import_bt_kwh",
            "import_variable_cost_chf",
            "fixed_cost_chf",
            "export_revenue_chf",
            "net_estimated_cost_chf",
            "is_complete",
        ]
    ].rename(
        columns={
            "label": "Mois",
            "import_ht_kwh": "Import HT [kWh]",
            "import_bt_kwh": "Import BT [kWh]",
            "import_variable_cost_chf": "Coût variable [CHF]",
            "fixed_cost_chf": "Frais fixes [CHF]",
            "export_revenue_chf": "Reprise PV [CHF]",
            "net_estimated_cost_chf": "Solde estimé [CHF]",
            "is_complete": "Complet",
        }
    )
    dataframe_with_number_format(
        monthly_display,
        {
            "Import HT [kWh]": "{:,.0f}",
            "Import BT [kWh]": "{:,.0f}",
            "Coût variable [CHF]": "{:,.2f}",
            "Frais fixes [CHF]": "{:,.2f}",
            "Reprise PV [CHF]": "{:,.2f}",
            "Solde estimé [CHF]": "{:,.2f}",
        },
    )

    st.subheader("Reprise PV par trimestre")
    st.caption(
        "La valorisation est affectée au trimestre civil de chaque kWh injecté. "
        "Les trimestres sans prix confirmé ne sont pas valorisés."
    )
    quarterly_display = quarterly_billing[
        [
            "label",
            "export_kwh",
            "energy_rate_ct_kwh",
            "go_rate_ct_kwh",
            "energy_revenue_chf",
            "go_revenue_chf",
            "export_revenue_chf",
            "export_unpriced_kwh",
        ]
    ].rename(
        columns={
            "label": "Trimestre",
            "export_kwh": "Injection [kWh]",
            "energy_rate_ct_kwh": "Énergie [ct/kWh]",
            "go_rate_ct_kwh": "GO [ct/kWh]",
            "energy_revenue_chf": "Reprise énergie [CHF]",
            "go_revenue_chf": "GO [CHF]",
            "export_revenue_chf": "Reprise totale [CHF]",
            "export_unpriced_kwh": "Injection non tarifée [kWh]",
        }
    )
    dataframe_with_number_format(
        quarterly_display,
        {
            "Injection [kWh]": "{:,.0f}",
            "Énergie [ct/kWh]": "{:,.3f}",
            "GO [ct/kWh]": "{:,.3f}",
            "Reprise énergie [CHF]": "{:,.2f}",
            "GO [CHF]": "{:,.2f}",
            "Reprise totale [CHF]": "{:,.2f}",
            "Injection non tarifée [kWh]": "{:,.0f}",
        },
    )


def show_profile_tab(metrics: dict[str, object], settings: AnalysisSettings) -> None:
    st.subheader("Profil et potentiel de pilotage")
    st.caption(
        "Le potentiel de décalage est un plafond théorique : pour chaque jour, "
        "il retient le minimum entre l’injection de la fenêtre solaire et le "
        "soutirage hors de cette fenêtre. Il ne constitue pas une économie garantie."
    )
    first, second, third, fourth = st.columns(4)
    with first:
        metric_with_caption(
            f"Import nuit ({settings.night_start_hour} h–{settings.night_end_hour} h)",
            kwh(metrics["night_import_kwh"]),
            f"{pct(metrics['night_import_share'] * 100)} de l’import · "
            f"{kwh(metrics['night_import_kwh_per_day'], 1)}/jour",
        )
    with second:
        metric_with_caption(
            f"Injection {settings.solar_start_hour} h–{settings.solar_end_hour} h",
            kwh(metrics["solar_export_kwh"]),
            f"{kwh(metrics['solar_export_kwh_per_day'], 1)}/jour",
        )
    with third:
        metric_with_caption(
            "Potentiel de décalage",
            kwh(metrics["shiftable_ceiling_kwh"]),
            f"Plafond : {kwh(metrics['shiftable_ceiling_kwh_per_day'], 1)}/jour",
        )
    with fourth:
        metric_with_caption(
            "Surplus actif moyen",
            kw(metrics["active_export_average_kw"]),
            f"{hours(metrics['active_export_hours'])} avec injection > 0,10 kW",
        )

    left, right = st.columns(2)
    with left:
        st.plotly_chart(
            threshold_hours_chart(metrics["hours_above_kw"]),
            width="stretch",
        )
        thresholds = pd.DataFrame(
            {
                "Seuil d’injection": [f">{value} kW" for value in metrics["hours_above_kw"]],
                "Durée observée [h]": list(metrics["hours_above_kw"].values()),
            }
        )
        dataframe_with_number_format(thresholds, {"Durée observée [h]": "{:,.0f}"})
    with right:
        st.plotly_chart(seasonal_energy_chart(metrics), width="stretch")
        st.caption(
            "Les saisons correspondent à : printemps (mars–mai), été (juin–août), "
            "automne (septembre–novembre) et hiver (décembre–février)."
        )

    st.subheader("Plages de soutirage récurrentes à investiguer")
    recurring = metrics["recurring_windows"]
    if recurring.empty:
        st.info(
            "Aucune plage suffisamment récurrente n’a été retenue avec les seuils prudents actuels."
        )
    else:
        st.caption(
            "Ces plages indiquent un comportement à rapprocher des équipements et "
            "programmations réels ; elles n’identifient pas un appareil automatiquement."
        )
        display = recurring[
            ["Plage", "Puissance médiane [kW]", "duration_h", "Fréquence"]
        ].rename(
            columns={
                "duration_h": "Durée [h]",
                "Fréquence": "Fréquence des jours",
            }
        )
        dataframe_with_number_format(
            display,
            {
                "Puissance médiane [kW]": "{:,.2f}",
                "Durée [h]": "{:,.2f}",
                "Fréquence des jours": "{:.0%}",
            },
        )


def show_typical_days_tab(
    data: pd.DataFrame, selected_years: list[int], settings: AnalysisSettings
) -> None:
    st.subheader("Journées types saisonnières")
    mode = st.radio(
        "Affichage",
        ("Comparer les années", "Moyenne globale des années sélectionnées"),
        horizontal=True,
    )
    st.caption(
        "Chaque courbe est la moyenne des mesures réelles à chaque quart d’heure. "
        "L’import est affiché au-dessus de zéro ; l’injection, en pointillé, au-dessous."
    )
    slots = list(st.columns(2)) + list(st.columns(2))
    for slot, season in zip(slots, SEASON_ORDER):
        with slot:
            profile = seasonal_typical_day(
                data,
                season,
                selected_years,
                grouped=mode.startswith("Moyenne"),
            )
            if profile.empty:
                st.info(f"Pas de mesure disponible pour {season.lower()}.")
            else:
                st.plotly_chart(
                    typical_day_chart(
                        profile,
                        season,
                        settings.solar_start_hour,
                        settings.solar_end_hour,
                    ),
                    width="stretch",
                    config={"displaylogo": False},
                )


def show_recommendations_tab(
    metrics: dict[str, object], quality, settings: AnalysisSettings
) -> None:
    st.subheader("Conseils Soleol")
    st.markdown(
        f'<div class="client-summary">{client_summary(metrics, settings)}</div>',
        unsafe_allow_html=True,
    )
    for recommendation in build_recommendations(metrics, quality, settings):
        evidence = "".join(f"<li>{item}</li>" for item in recommendation["evidence"])
        evidence_html = f"<ul>{evidence}</ul>" if evidence else ""
        st.markdown(
            f"""
            <div class="advice-card">
                <div class="advice-category">{recommendation["category"]}</div>
                <div class="advice-title">{recommendation["title"]}</div>
                <div>{recommendation["text"]}</div>
                {evidence_html}
            </div>
            """,
            unsafe_allow_html=True,
        )
    st.caption(
        "Important : les flux import/export ne permettent pas de reconstituer la "
        "consommation totale, la production photovoltaïque totale ni l’appareil responsable "
        "d’un pic. Une batterie n’est donc pas dimensionnée dans cette version."
    )


def show_data_tab(
    data: pd.DataFrame,
    annual: pd.DataFrame,
    monthly: pd.DataFrame,
    quality,
    convention: str,
    annual_billing: pd.DataFrame,
    monthly_billing: pd.DataFrame,
    export_rate_table: pd.DataFrame,
) -> None:
    st.subheader("Qualité des données et export")
    left, middle, right, fourth = st.columns(4)
    with left:
        metric_with_caption("Mesures lues", swiss_number(quality.imported_rows))
    with middle:
        metric_with_caption("Après déduplication", swiss_number(quality.retained_rows))
    with right:
        metric_with_caption(
            "Lacunes estimées", swiss_number(quality.estimated_missing_intervals)
        )
    with fourth:
        metric_with_caption(
            "Valeurs non numériques", swiss_number(quality.invalid_numeric_values)
        )

    st.caption(
        "Convention active : "
        + (
            "horodatage de fin d’intervalle (format Groupe E)."
            if convention == "end"
            else "horodatage de début d’intervalle."
        )
        + " Les dates Excel sans fuseau sont conservées telles quelles ; l’heure répétée "
        "au passage à l’heure d’hiver n’est jamais reconstruite artificiellement."
    )
    source_table = pd.DataFrame(quality.source_rows)
    if not source_table.empty:
        st.dataframe(source_table, width="stretch", hide_index=True)

    simultaneous = (
        data["valid_measurement"] & (data["import_kw"] > 0.10) & (data["export_kw"] > 0.10)
    ).sum()
    if simultaneous:
        st.info(
            f"{swiss_number(simultaneous)} pas affichent simultanément import et injection. "
            "Les deux flux sont conservés séparément : cela peut résulter de l’agrégation "
            "au sein d’un quart d’heure et n’est pas supprimé automatiquement."
        )
    for warning in quality.warnings:
        st.warning(warning)

    annual_export = annual.copy()
    monthly_export = monthly.copy()
    annual_csv = annual_export.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig")
    monthly_csv = monthly_export.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig")
    annual_billing_csv = annual_billing.to_csv(index=False, sep=";", decimal=",").encode(
        "utf-8-sig"
    )
    monthly_billing_csv = monthly_billing.to_csv(index=False, sep=";", decimal=",").encode(
        "utf-8-sig"
    )
    export_rates_csv = export_rate_table.to_csv(index=False, sep=";", decimal=",").encode(
        "utf-8-sig"
    )
    col_one, col_two, col_three, col_four, col_five = st.columns(5)
    with col_one:
        st.download_button(
            "Télécharger la synthèse annuelle (CSV)",
            data=annual_csv,
            file_name="synthese_annuelle_energie.csv",
            mime="text/csv",
        )
    with col_two:
        st.download_button(
            "Télécharger la synthèse mensuelle (CSV)",
            data=monthly_csv,
            file_name="synthese_mensuelle_energie.csv",
            mime="text/csv",
        )
    with col_three:
        st.download_button(
            "Télécharger l’estimation tarifaire annuelle (CSV)",
            data=annual_billing_csv,
            file_name="estimation_tarifaire_annuelle.csv",
            mime="text/csv",
        )
    with col_four:
        st.download_button(
            "Télécharger l’estimation tarifaire mensuelle (CSV)",
            data=monthly_billing_csv,
            file_name="estimation_tarifaire_mensuelle.csv",
            mime="text/csv",
        )
    with col_five:
        st.download_button(
            "Télécharger les paramètres de reprise (CSV)",
            data=export_rates_csv,
            file_name="parametres_reprise_pv.csv",
            mime="text/csv",
        )


def main() -> None:
    inject_style()
    with st.sidebar:
        st.markdown("## Données d’analyse")
        uploaded_files = st.file_uploader(
            "Courbes Excel",
            type=["xlsx", "xlsm"],
            accept_multiple_files=True,
            help="Une colonne Date et une colonne Soutirage/Import ou Surplus/Export sont recherchées automatiquement.",
        )
        st.markdown("---")
        st.markdown("### Convention de date")
        convention_label = st.radio(
            "Les dates indiquent",
            (
                "La fin de l’intervalle — Groupe E",
                "Le début de l’intervalle",
            ),
            help=(
                "Les fichiers Groupe E testés commencent à 00:15 et se terminent à 00:00 "
                "le lendemain : ils sont donc interprétés comme des fins de quart d’heure."
            ),
        )
        st.markdown("### Fenêtres de diagnostic")
        with st.expander("Adapter les heures", expanded=False):
            night_start = st.slider("Début nuit", 0, 23, 23)
            night_end = st.slider("Fin nuit", 0, 23, 6)
            solar_start = st.slider("Début fenêtre solaire", 0, 23, 10)
            solar_end = st.slider("Fin fenêtre solaire", 1, 24, 16)

    if not uploaded_files:
        show_empty_state()
        return

    imported: list[ImportedFile] = []
    errors: list[str] = []
    with st.spinner("Lecture et contrôle des courbes…"):
        for uploaded in uploaded_files:
            try:
                imported.append(parse_uploaded_file(uploaded.name, uploaded.getvalue()))
            except Exception as exc:  # noqa: BLE001 - message utile au conseiller.
                errors.append(f"{uploaded.name} : {exc}")
    for error in errors:
        st.error(error)
    if not imported:
        return

    combined, quality = combine_imports(imported)
    convention = "end" if convention_label.startswith("La fin") else "start"
    settings = AnalysisSettings(
        night_start_hour=night_start,
        night_end_hour=night_end,
        solar_start_hour=solar_start,
        solar_end_hour=solar_end,
        timestamp_convention=convention,
    )
    all_data = add_analysis_flags(apply_timestamp_convention(combined, convention), settings)
    available_years = sorted(all_data["year"].unique().tolist())
    if not available_years:
        st.error("Aucune date exploitable n’a été trouvée.")
        return

    with st.sidebar:
        st.markdown("---")
        selected_years = st.multiselect(
            "Années affichées",
            available_years,
            default=available_years,
        )
    if not selected_years:
        st.warning("Sélectionnez au moins une année.")
        return
    with st.sidebar:
        st.markdown("---")
        st.markdown("### Profil GRD")
        grd = st.selectbox(
            "Gestionnaire de réseau",
            GRD_NAMES,
            help="La version actuelle prend en charge uniquement Groupe E et Romande Energie.",
        )
        offer = st.selectbox(
            "Tarif de référence",
            offers_for_grd(grd),
            help="Vérifiez toujours le produit effectivement indiqué sur la facture du client.",
        )
    data = all_data[all_data["year"].isin(selected_years)].copy()
    annual = annual_summary(data)
    monthly = monthly_summary(data)
    metrics = profile_metrics(data, settings)

    show_header(client_metadata(imported), data)
    tabs = st.tabs(
        [
            "Synthèse",
            "Tarifs GRD",
            "Profil & pilotage",
            "Journées types",
            "Conseils Soleol",
            "Données & export",
        ]
    )
    with tabs[1]:
        rates_by_year, include_go, export_rate_table = show_tariff_configuration(
            grd, offer, selected_years
        )
    priced = apply_billing_rates(data, grd, rates_by_year, include_go=include_go)
    fixed_billing = fixed_charges_by_month(priced, rates_by_year)
    annual_billing = billing_summary(priced, fixed_billing)
    monthly_billing = monthly_billing_summary(priced, fixed_billing)
    quarterly_billing = quarterly_export_summary(priced)
    with tabs[0]:
        show_summary_tab(data, all_data, annual, monthly, selected_years)
    with tabs[1]:
        show_tariff_results(
            priced,
            annual_billing,
            monthly_billing,
            quarterly_billing,
            grd,
            include_go,
        )
    with tabs[2]:
        show_profile_tab(metrics, settings)
    with tabs[3]:
        show_typical_days_tab(data, selected_years, settings)
    with tabs[4]:
        show_recommendations_tab(metrics, quality, settings)
    with tabs[5]:
        show_data_tab(
            data,
            annual,
            monthly,
            quality,
            convention,
            annual_billing,
            monthly_billing,
            export_rate_table,
        )


if __name__ == "__main__":
    main()
