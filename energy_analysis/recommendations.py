"""Recommandations déterministes et explicables, jamais prescriptives sur la batterie."""

from __future__ import annotations

from typing import Any

import pandas as pd

from .config import AnalysisSettings
from .formatting import hours, kw, kwh, pct
from .models import DataQuality


def _recommendation(
    priority: int,
    category: str,
    title: str,
    text: str,
    evidence: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "priority": priority,
        "category": category,
        "title": title,
        "text": text,
        "evidence": evidence or [],
    }


def build_recommendations(
    metrics: dict[str, Any],
    quality: DataQuality,
    settings: AnalysisSettings,
) -> list[dict[str, Any]]:
    """Construit les messages client selon des règles visibles et prudentes."""

    if not metrics:
        return []
    recommendations: list[dict[str, Any]] = []
    missing_rate = quality.estimated_missing_intervals / max(1, quality.retained_rows)
    if quality.conflicting_duplicates or missing_rate > 0.02:
        recommendations.append(
            _recommendation(
                0,
                "Qualité des données",
                "Vérifier les mesures avant toute décision d’investissement",
                "Certaines lacunes ou valeurs contradictoires ont été détectées. "
                "Les conclusions restent indicatives tant que les mesures ne sont pas "
                "complétées ou confirmées.",
                [
                    f"{quality.estimated_missing_intervals} pas de mesure manquant(s) estimé(s)",
                    f"{quality.conflicting_duplicates} doublon(s) contradictoire(s)",
                ],
            )
        )

    if not metrics.get("export_available", True):
        recommendations.append(
            _recommendation(
                0,
                "Donnée photovoltaïque",
                "Compléter l’injection réseau avant de chiffrer la reprise PV",
                "Le fichier permet d’analyser les consommations, mais ne fournit pas l’injection "
                "réseau. Il serait trompeur d’afficher un revenu de reprise, un surplus solaire "
                "ou un potentiel de batterie sans cette mesure.",
            )
        )

    pilotage_possible = (
        metrics["solar_export_kwh_per_day"] >= 2.0
        and metrics["outside_solar_import_kwh_per_day"] >= 2.0
        and metrics["overlap_days_ratio"] >= 0.40
    )
    if pilotage_possible:
        recommendations.append(
            _recommendation(
                1,
                "Priorité : pilotage",
                "Déplacer les usages pilotables vers les heures solaires",
                "Votre profil présente une injection réseau régulière pendant la "
                "fenêtre solaire, alors que du soutirage demeure observé en dehors "
                "de cette période. La première mesure recommandée consiste à "
                "programmer les usages flexibles sur les heures de surplus.",
                [
                    f"{kwh(metrics['solar_export_kwh_per_day'], 1)}/jour injectés entre "
                    f"{settings.solar_start_hour} h et {settings.solar_end_hour} h",
                    f"{kwh(metrics['outside_solar_import_kwh_per_day'], 1)}/jour soutirés "
                    "hors de cette fenêtre",
                    f"Plafond théorique de décalage : "
                    f"{kwh(metrics['shiftable_ceiling_kwh_per_day'], 1)}/jour",
                ],
            )
        )
        recommendations.append(
            _recommendation(
                2,
                "Usages à examiner",
                "Cibler en priorité l’ECS, la PAC et la recharge de véhicule",
                "Vérifiez les programmations du chauffe-eau, de la pompe à chaleur "
                "et, si présent, de la recharge de véhicule électrique. Les appareils "
                "ménagers programmables (lave-vaisselle, lave-linge et sèche-linge) "
                "peuvent également être décalés vers la journée.",
                [
                    f"Surplus actif moyen : {kw(metrics['active_export_average_kw'])}",
                    f"Disponibilité au-dessus de 2 kW : {hours(metrics['hours_above_kw'][2])}",
                ],
            )
        )

    if metrics["night_import_share"] >= 0.15 and metrics["night_persistence_ratio"] >= 0.70:
        recommendations.append(
            _recommendation(
                2,
                "Consommation nocturne",
                "Investiguer les consommations persistantes la nuit",
                "Une part significative du soutirage est observée de nuit. Avant "
                "tout investissement, il est conseillé d’identifier les consommations "
                "de fond et les équipements programmés hors des heures solaires.",
                [
                    f"{kwh(metrics['night_import_kwh'], 0)} sur la période",
                    f"{pct(metrics['night_import_share'] * 100)} de l’import total",
                    f"Puissance nocturne moyenne : {kw(metrics['night_average_kw'])}",
                ],
            )
        )

    windows: pd.DataFrame = metrics["recurring_windows"]
    if not windows.empty:
        first = windows.iloc[0]
        recommendations.append(
            _recommendation(
                3,
                "Profil récurrent",
                "Contrôler une plage de soutirage élevée récurrente",
                "Une plage de soutirage élevée revient régulièrement au même horaire. "
                "Les mesures réseau ne permettent pas d’identifier l’appareil : cette "
                "plage doit être rapprochée des programmations réelles du site.",
                [
                    f"{first['Plage']}",
                    f"Puissance médiane : {kw(first['Puissance médiane [kW]'])}",
                    f"Fréquence : {pct(first['Fréquence'] * 100)} des jours observés",
                ],
            )
        )

    winter = metrics["seasonal"].get("Hiver", {})
    shoulder_export = (
        metrics["seasonal"].get("Printemps", {}).get("export_kwh_per_day", 0.0)
        + metrics["seasonal"].get("Été", {}).get("export_kwh_per_day", 0.0)
    ) / 2
    if shoulder_export > 0 and winter.get("export_kwh_per_day", 0.0) < shoulder_export * 0.35:
        recommendations.append(
            _recommendation(
                4,
                "Saisonnalité",
                "Tenir compte de la limite hivernale",
                "L’injection réseau disponible est nettement plus faible en hiver. "
                "Une batterie peut décaler une énergie disponible sur une journée, "
                "mais elle ne remplace pas la production photovoltaïque absente "
                "durant la saison hivernale.",
                [
                    f"Injection moyenne hiver : "
                    f"{kwh(winter.get('export_kwh_per_day', 0.0), 1)}/jour",
                    f"Printemps–été : {kwh(shoulder_export, 1)}/jour en moyenne",
                ],
            )
        )

    if pilotage_possible:
        recommendations.append(
            _recommendation(
                5,
                "Batterie — seconde étape",
                "Étudier le stockage après optimisation du pilotage",
                "Une simulation de batterie pourra être réalisée dans un second "
                "temps, sur la base du profil résiduel après pilotage. Cette version "
                "n’estime volontairement ni capacité, ni gain financier sans les "
                "tarifs et le scénario de pilotage du client.",
            )
        )
    if not recommendations:
        recommendations.append(
            _recommendation(
                1,
                "Analyse à compléter",
                "Poursuivre l’analyse avec les usages du site",
                "Les flux réseau seuls ne permettent pas d’identifier la "
                "consommation totale ni les appareils en fonctionnement. Un relevé "
                "des équipements et de leurs horaires permettra de cibler les "
                "actions les plus utiles.",
            )
        )
    return sorted(recommendations, key=lambda item: item["priority"])


def client_summary(metrics: dict[str, Any], settings: AnalysisSettings) -> str:
    """Paragraphe prêt à être repris dans un échange client."""

    if not metrics:
        return ""
    if not metrics.get("export_available", True):
        return (
            "Cette courbe permet d’identifier les consommations et leurs horaires. Elle ne contient "
            "pas l’injection réseau : le revenu photovoltaïque, le surplus exporté et le potentiel "
            "de stockage ne sont donc pas chiffrés. La première étape consiste à analyser les usages "
            "consommateurs et leurs possibilités de programmation."
        )
    if (
        metrics["solar_export_kwh_per_day"] >= 2.0
        and metrics["outside_solar_import_kwh_per_day"] >= 2.0
    ):
        return (
            "Votre profil présente une injection réseau importante entre "
            f"{settings.solar_start_hour} h et {settings.solar_end_hour} h, "
            "tandis qu’une partie du soutirage intervient en dehors de cette "
            "période, notamment la nuit. La première mesure recommandée consiste "
            "à déplacer les consommateurs pilotables vers les heures de surplus "
            "solaire — chauffe-eau, PAC, recharge de véhicule et appareils "
            "programmables — avant d’envisager un système de stockage."
        )
    return (
        "Les mesures réseau permettent d’identifier les périodes de soutirage et "
        "d’injection. Avant toute étude de stockage, il est recommandé de rapprocher "
        "ces périodes des usages réellement pilotables du site afin de privilégier "
        "les actions sans investissement."
    )
