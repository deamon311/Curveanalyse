"""Profils tarifaires limités aux deux GRD pris en charge par Soleol.

Les horaires HT/BT sont des règles de calendrier. Les montants restent des
paramètres de facture : une commune, une offre d'énergie, la puissance de
l'installation PV ou la cession des garanties d'origine peuvent les modifier.

Les valeurs de reprise ci-dessous sont donc séparées entre ``energy`` et
``go`` (garanties d'origine), et peuvent être corrigées dans l'interface.
``None`` signifie que le trimestre n'était pas encore publié à la date de la
référence, pas que la reprise vaut zéro.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

GRD_NAMES = ("Groupe E", "Romande Energie")
QUARTERS = (1, 2, 3, 4)

COMPONENTS = ("energy", "distribution", "swissgrid", "taxes")


def _component_rates(
    *,
    energy_ht: float | None = None,
    energy_bt: float | None = None,
    distribution_ht: float | None = None,
    distribution_bt: float | None = None,
    swissgrid_ht: float | None = None,
    swissgrid_bt: float | None = None,
    taxes_ht: float | None = None,
    taxes_bt: float | None = None,
    energy_fixed: float | None = None,
    distribution_fixed: float | None = None,
    swissgrid_fixed: float | None = None,
    taxes_fixed: float | None = None,
    energy_fixed_year: float | None = None,
    distribution_fixed_year: float | None = None,
    swissgrid_fixed_year: float | None = None,
    taxes_fixed_year: float | None = None,
    vat_purchase_pct: float | None = None,
) -> dict[str, float | None]:
    """Construit une grille de tarifs en ct/kWh et CHF/mois ou CHF/an."""

    return {
        "energy_ht_ct_kwh": energy_ht,
        "energy_bt_ct_kwh": energy_bt,
        "distribution_ht_ct_kwh": distribution_ht,
        "distribution_bt_ct_kwh": distribution_bt,
        "swissgrid_ht_ct_kwh": swissgrid_ht,
        "swissgrid_bt_ct_kwh": swissgrid_bt,
        "taxes_ht_ct_kwh": taxes_ht,
        "taxes_bt_ct_kwh": taxes_bt,
        "energy_fixed_chf_month": energy_fixed,
        "distribution_fixed_chf_month": distribution_fixed,
        "swissgrid_fixed_chf_month": swissgrid_fixed,
        "taxes_fixed_chf_month": taxes_fixed,
        "energy_fixed_chf_year": energy_fixed_year,
        "distribution_fixed_chf_year": distribution_fixed_year,
        "swissgrid_fixed_chf_year": swissgrid_fixed_year,
        "taxes_fixed_chf_year": taxes_fixed_year,
        "vat_purchase_pct": vat_purchase_pct,
    }


_EMPTY_COMPONENT_RATES = _component_rates()


def _quarterly(value: float | None) -> dict[int, float | None]:
    """Réplique une valeur dans les quatre trimestres civils."""

    return {quarter: value for quarter in QUARTERS}


_GROUP_E_PLUS_DOUBLE_2025 = _component_rates(
    energy_ht=16.25,
    energy_bt=11.95,
    distribution_ht=8.27,
    distribution_bt=3.59,
    # La facture sépare Swissgrid (1.63) et la réserve d'hiver (0.23).
    # Elles sont regroupées ici, mais restent identifiées dans la note.
    swissgrid_ht=1.86,
    swissgrid_bt=1.86,
    taxes_ht=2.30,
    taxes_bt=2.30,
    energy_fixed=0.0,
    distribution_fixed_year=120.0,
    swissgrid_fixed=0.0,
    taxes_fixed=0.0,
    vat_purchase_pct=8.1,
)


# Sources vérifiées lors de l'intégration (01.10.2026) :
# - Groupe E : https://www.groupe-e.ch/fr/electricite/star
# - Groupe E : https://www.groupe-e.ch/fr/solaire/offre-reprise
# - OFEN : https://www.bfe.admin.ch/fr/prix-de-marche-de-reference
# - Romande Energie : https://www.romande-energie.ch/solaire/prix-de-reprise
# - Fiches Romande Energie 2025/2026 (tarif Double, Energie Suisse).
_PROFILES: dict[str, dict[str, Any]] = {
    "Groupe E": {
        "schedule_by_year": {
            2025: {
                "high_periods": ((7.0, 21.0),),
                "weekend_low": False,
                "label": "HT 07:00–21:00, tous les jours",
            },
            2026: {
                "high_periods": ((7.0, 12.0), (17.0, 23.0)),
                "weekend_low": False,
                "label": "HT 07:00–12:00 et 17:00–23:00, tous les jours",
            },
        },
        "offers": (
            "PLUS tarif double interruptible — référence facture 2025",
            "Tarif double — à compléter selon facture",
        ),
        # Référence explicitement issue des quatre factures fournies : Lully
        # FR, tarif PLUS double interruptible, villa solaire 10 kVA. Elle est
        # utile comme point de départ, mais n'est pas un barème universel
        # Groupe E (produit, commune, puissance et taxes peuvent différer).
        "component_rates_by_year": {
            2025: _GROUP_E_PLUS_DOUBLE_2025,
            2026: _EMPTY_COMPONENT_RATES,
        },
        "component_notes": {
            2025: (
                "Profil de référence issu de quatre factures Groupe E 2025 : "
                "PLUS tarif double interruptible, Lully FR, villa solaire 10 kVA. "
                "Swissgrid 1.63 + réserve d'hiver 0.23 = 1.86 ct/kWh ; "
                "montant de base distribution 120 CHF/an ; TVA achats 8.1 %."
            ),
            2026: (
                "Aucune facture Groupe E 2026 n'a encore été intégrée pour ce produit : "
                "recopier les composantes de la facture du client."
            ),
        },
        "export_by_year": {
            2017: {
                "energy_ct_kwh": _quarterly(8.50),
                "go_ct_kwh": _quarterly(0.80),
                "total_cap_ct_kwh": _quarterly(None),
                "source": "Historique Groupe E transmis par Soleol",
                "note": "GO à inclure uniquement si elle a été cédée au GRD.",
            },
            2018: {
                "energy_ct_kwh": _quarterly(7.30),
                "go_ct_kwh": _quarterly(2.00),
                "total_cap_ct_kwh": _quarterly(None),
                "source": "Historique Groupe E transmis par Soleol",
                "note": "GO à inclure uniquement si elle a été cédée au GRD.",
            },
            2019: {
                "energy_ct_kwh": _quarterly(7.30),
                "go_ct_kwh": _quarterly(2.00),
                "total_cap_ct_kwh": _quarterly(None),
                "source": "Historique Groupe E transmis par Soleol",
                "note": "GO à inclure uniquement si elle a été cédée au GRD.",
            },
            2020: {
                "energy_ct_kwh": _quarterly(7.30),
                "go_ct_kwh": _quarterly(2.00),
                "total_cap_ct_kwh": _quarterly(None),
                "source": "Historique Groupe E transmis par Soleol",
                "note": "GO à inclure uniquement si elle a été cédée au GRD.",
            },
            2021: {
                "energy_ct_kwh": _quarterly(7.30),
                "go_ct_kwh": _quarterly(2.00),
                "total_cap_ct_kwh": _quarterly(None),
                "source": "Historique Groupe E transmis par Soleol",
                "note": "GO à inclure uniquement si elle a été cédée au GRD.",
            },
            2022: {
                "energy_ct_kwh": _quarterly(7.30),
                "go_ct_kwh": _quarterly(2.00),
                "total_cap_ct_kwh": _quarterly(None),
                "source": "Historique Groupe E transmis par Soleol",
                "note": "GO à inclure uniquement si elle a été cédée au GRD.",
            },
            2023: {
                "energy_ct_kwh": _quarterly(11.45),
                "go_ct_kwh": _quarterly(3.00),
                "total_cap_ct_kwh": _quarterly(None),
                "source": "Historique Groupe E transmis par Soleol",
                "note": "GO à inclure uniquement si elle a été cédée au GRD.",
            },
            2024: {
                "energy_ct_kwh": _quarterly(11.45),
                "go_ct_kwh": _quarterly(3.00),
                "total_cap_ct_kwh": _quarterly(None),
                "source": "Historique Groupe E transmis par Soleol",
                "note": "GO à inclure uniquement si elle a été cédée au GRD.",
            },
            2025: {
                # Le plancher de 6 ct/kWh pour les petites installations est
                # repris ici : il est confirmé par les factures T2/T3 fournies.
                "energy_ct_kwh": {1: 10.380, 2: 6.000, 3: 6.000, 4: 9.508},
                "go_ct_kwh": {1: 4.0, 2: 4.0, 3: 4.0, 4: 4.0},
                "total_cap_ct_kwh": _quarterly(None),
                "source": "Factures Groupe E 2025 + historique de reprise Soleol",
                "note": (
                    "Énergie seule confirmée sur les factures fournies : 10.38 / 6.00 / "
                    "6.00 / 9.51 ct/kWh. Les 4 ct/kWh de GO sont distincts et ne doivent "
                    "être inclus que si le client les a effectivement cédés au GRD."
                ),
            },
            2026: {
                "energy_ct_kwh": {1: 10.266, 2: 6.000, 3: None, 4: None},
                "go_ct_kwh": {1: 3.0, 2: 1.0, 3: 1.0, 4: 3.0},
                "total_cap_ct_kwh": {1: 10.96, 2: 10.96, 3: 10.96, 4: 10.96},
                "source": "OFEN / offre de reprise Groupe E",
                "note": (
                    "T1/T2 : énergie effective pour petite installation avec plancher à 6 ct/kWh. "
                    "Si la GO est cédée, le total est plafonné à 10.96 ct/kWh pour une "
                    "installation <100 kVA avec autoconsommation ; n'activer le plafond que "
                    "si ces conditions sont confirmées. T3/T4 restent à renseigner."
                ),
            },
        },
    },
    "Romande Energie": {
        "schedule_by_year": {
            2025: {
                "high_periods": ((17.0, 22.0),),
                "weekend_low": True,
                "label": "HT lundi–vendredi 17:00–22:00 ; BT le reste du temps",
            },
            2026: {
                "high_periods": ((17.0, 22.0),),
                "weekend_low": True,
                "label": "HT lundi–vendredi 17:00–22:00 ; BT le reste du temps",
            },
        },
        "offers": ("Double — Energie Suisse", "Double — Energie Romande"),
        # Valeurs hors TVA de la fiche tarifaire résidentielle/PME "Double".
        # Swissgrid incorpore aussi la réserve hivernale nationale connue dans
        # la fiche. Les taxes locales restent à compléter par commune.
        "component_rates_by_year": {
            2025: _component_rates(
                energy_ht=16.68,
                energy_bt=11.81,
                distribution_ht=14.34,
                distribution_bt=8.43,
                swissgrid_ht=2.55,
                swissgrid_bt=1.71,
                taxes_ht=2.30,
                taxes_bt=2.30,
                energy_fixed=0.0,
                distribution_fixed=9.00,
                swissgrid_fixed=0.0,
                taxes_fixed=0.0,
                vat_purchase_pct=8.1,
            ),
            2026: _component_rates(
                energy_ht=18.28,
                energy_bt=12.94,
                distribution_ht=12.22,
                distribution_bt=7.19,
                swissgrid_ht=2.12,
                swissgrid_bt=1.53,
                taxes_ht=2.30,
                taxes_bt=2.30,
                energy_fixed=0.0,
                distribution_fixed=2.50,
                swissgrid_fixed=0.0,
                taxes_fixed=0.0,
                vat_purchase_pct=8.1,
            ),
        },
        "component_notes": {
            2025: (
                "Préréglage : tarif Double, offre Energie Suisse, hors TVA et hors "
                "taxes cantonales/communales."
            ),
            2026: (
                "Préréglage : tarif Double, offre Energie Suisse, hors TVA et hors "
                "taxes cantonales/communales."
            ),
        },
        "export_by_year": {
            2025: {
                "energy_ct_kwh": {1: 8.0, 2: 8.0, 3: 8.0, 4: 8.0},
                "go_ct_kwh": {1: None, 2: None, 3: None, 4: None},
                "total_cap_ct_kwh": _quarterly(None),
                "source": "Valeur du fichier fourni — à confirmer sur la facture 2025",
                "note": "Le modèle trimestriel officiel est appliqué dès 2026.",
            },
            2026: {
                "energy_ct_kwh": {1: 10.26, 2: 3.89, 3: None, 4: None},
                "go_ct_kwh": {1: 1.5, 2: 0.5, 3: 0.5, 4: 1.5},
                "total_cap_ct_kwh": _quarterly(None),
                "source": "Prix de reprise Romande Energie / OFEN",
                "note": (
                    "Au 01.10.2026, T3 et T4 restent à renseigner à leur publication. "
                    "Un prix minimal peut s'appliquer à certaines installations."
                ),
            },
        },
    },
}


def profile_for_year(grd: str, year: int) -> dict[str, Any]:
    """Retourne le calendrier HT/BT du GRD pour une année.

    Pour une nouvelle année non encore documentée, le dernier calendrier connu
    est proposé uniquement comme aide à la saisie et l'appelant doit afficher un
    avertissement. Cela permet d'ajouter des courbes sans modifier le code,
    sans prétendre connaître un tarif futur.
    """

    if grd not in _PROFILES:
        raise ValueError(f"GRD inconnu : {grd}. Choisir Groupe E ou Romande Energie.")
    profile = _PROFILES[grd]
    schedules = profile["schedule_by_year"]
    reference_year = int(year)
    if reference_year not in schedules:
        past = [candidate for candidate in schedules if candidate <= reference_year]
        selected_year = max(past) if past else min(schedules)
    else:
        selected_year = reference_year
    result = deepcopy(schedules[selected_year])
    result.update(
        {
            "grd": grd,
            "year": reference_year,
            "schedule_reference_year": selected_year,
            "schedule_needs_confirmation": selected_year != reference_year,
        }
    )
    return result


def offers_for_grd(grd: str) -> tuple[str, ...]:
    """Produits de départ affichés dans l'interface."""

    if grd not in _PROFILES:
        raise ValueError(f"GRD inconnu : {grd}. Choisir Groupe E ou Romande Energie.")
    return tuple(_PROFILES[grd]["offers"])


def component_rates_for_year(grd: str, year: int, offer: str | None = None) -> dict[str, Any]:
    """Préréglages de facture, toujours modifiables par le conseiller."""

    if grd not in _PROFILES:
        raise ValueError(f"GRD inconnu : {grd}. Choisir Groupe E ou Romande Energie.")
    profile = _PROFILES[grd]
    rates_by_year = profile["component_rates_by_year"]
    requested_year = int(year)
    reference_year: int | None = requested_year if requested_year in rates_by_year else None
    rates = (
        deepcopy(rates_by_year[requested_year])
        if reference_year is not None
        else deepcopy(_EMPTY_COMPONENT_RATES)
    )
    note = (
        profile["component_notes"][requested_year]
        if reference_year is not None
        else "Aucun tarif de facture confirmé pour cette année : recopier la facture du client."
    )
    if grd == "Groupe E" and offer == "Tarif double — à compléter selon facture":
        rates = deepcopy(_EMPTY_COMPONENT_RATES)
        note = "Profil volontairement vide : recopier les composantes de la facture client."
        reference_year = None
    if grd == "Romande Energie" and offer == "Double — Energie Romande":
        for key in ("energy_ht_ct_kwh", "energy_bt_ct_kwh"):
            if rates[key] is not None:
                rates[key] += 1.5
        note += " Offre Energie Romande : +1.5 ct/kWh sur la composante énergie."
    return {
        "year": int(year),
        "reference_year": reference_year,
        "rates": rates,
        "note": note,
        "needs_confirmation": reference_year != requested_year or grd == "Groupe E",
    }


def export_rates_for_year(grd: str, year: int) -> dict[str, Any]:
    """Valeurs trimestrielles de reprise affichées dans l'éditeur tarifaire."""

    if grd not in _PROFILES:
        raise ValueError(f"GRD inconnu : {grd}. Choisir Groupe E ou Romande Energie.")
    profile = _PROFILES[grd]
    by_year = profile["export_by_year"]
    if int(year) in by_year:
        reference_year: int | None = int(year)
        needs_confirmation = False
        result = deepcopy(by_year[reference_year])
    else:
        reference_year = None
        needs_confirmation = True
        result = {
            "energy_ct_kwh": _quarterly(None),
            "go_ct_kwh": _quarterly(None),
            "total_cap_ct_kwh": _quarterly(None),
            "source": "À compléter depuis le contrat ou la facture client",
            "note": "Aucun tarif de reprise confirmé pour cette année.",
        }
    result.update(
        {
            "year": int(year),
            "reference_year": reference_year,
            "needs_confirmation": needs_confirmation,
        }
    )
    return result
