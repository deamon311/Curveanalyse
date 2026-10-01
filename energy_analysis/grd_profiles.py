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
) -> dict[str, float | None]:
    """Construit une grille de tarifs en ct/kWh et CHF/mois."""

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
    }


_EMPTY_COMPONENT_RATES = _component_rates()


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
        "offers": ("Tarif double — à ventiler selon facture",),
        # Les fiches tarifaires détaillées Groupe E dépendent notamment du
        # produit souscrit. Les 29.32 / 19.27 ct/kWh du fichier fourni sont un
        # total variable non ventilé : ils ne sont volontairement pas répartis
        # artificiellement parmi les quatre composantes de facture.
        "component_rates_by_year": {
            2025: _EMPTY_COMPONENT_RATES,
            2026: _EMPTY_COMPONENT_RATES,
        },
        "component_notes": {
            2025: "Recopier les quatre composantes de la facture Groupe E du client.",
            2026: (
                "Le fichier fourni indique 29.32 ct/kWh HT et 19.27 ct/kWh BT, "
                "mais sans ventilation énergie / réseau / Swissgrid / taxes."
            ),
        },
        "export_by_year": {
            2025: {
                "energy_ct_kwh": {1: 10.380, 2: 2.759, 3: 5.731, 4: 9.508},
                "go_ct_kwh": {1: 4.0, 2: 4.0, 3: 4.0, 4: 4.0},
                "source": "Référence OFEN + GO Groupe E (à confirmer selon contrat)",
                "note": (
                    "Prix de marché PV OFEN. Groupe E peut appliquer une protection "
                    "ou un plafond selon la puissance et la cession de GO."
                ),
            },
            2026: {
                "energy_ct_kwh": {1: 10.266, 2: 3.896, 3: None, 4: None},
                "go_ct_kwh": {1: 3.0, 2: 1.0, 3: 1.0, 4: 3.0},
                "source": "OFEN / offre de reprise Groupe E",
                "note": (
                    "Au 01.10.2026, seuls T1 et T2 sont publiés. Pour une installation "
                    "PV < 30 kW, Groupe E indique un minimum de 6 ct/kWh lorsque le "
                    "prix OFEN est inférieur ; vérifier le montant réellement facturé."
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
                "source": "Valeur du fichier fourni — à confirmer sur la facture 2025",
                "note": "Le modèle trimestriel officiel est appliqué dès 2026.",
            },
            2026: {
                "energy_ct_kwh": {1: 10.26, 2: 3.89, 3: None, 4: None},
                "go_ct_kwh": {1: 1.5, 2: 0.5, 3: 0.5, 4: 1.5},
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
    if int(year) in rates_by_year:
        reference_year = int(year)
    else:
        past = [candidate for candidate in rates_by_year if candidate <= int(year)]
        reference_year = max(past) if past else max(rates_by_year)
    rates = deepcopy(rates_by_year[reference_year])
    note = profile["component_notes"][reference_year]
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
        "needs_confirmation": reference_year != int(year) or grd == "Groupe E",
    }


def export_rates_for_year(grd: str, year: int) -> dict[str, Any]:
    """Valeurs trimestrielles de reprise affichées dans l'éditeur tarifaire."""

    if grd not in _PROFILES:
        raise ValueError(f"GRD inconnu : {grd}. Choisir Groupe E ou Romande Energie.")
    profile = _PROFILES[grd]
    by_year = profile["export_by_year"]
    if int(year) in by_year:
        reference_year = int(year)
        needs_confirmation = False
    else:
        reference_year = max(by_year)
        needs_confirmation = True
    result = deepcopy(by_year[reference_year])
    result.update(
        {
            "year": int(year),
            "reference_year": reference_year,
            "needs_confirmation": needs_confirmation,
        }
    )
    return result
