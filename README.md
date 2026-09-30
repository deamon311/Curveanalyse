# Analyse énergétique Soleol

Application Streamlit destinée au conseil énergétique de clients photovoltaïques.
Elle lit des courbes de charge réseau, visualise les importations et injections
réelles, puis priorise le déplacement des usages pilotables avant toute étude de
batterie.

## Ce que fait la V2

- charge plusieurs fichiers Excel sans modifier le code pour ajouter une année ;
- détecte une ligne d’en-tête `Date`, `Soutirage / Import` et `Surplus / Export` ;
- reconnaît `kW` et `kWh par intervalle` dans les libellés de colonnes ;
- déduplique les mêmes horodatages sans les additionner ;
- conserve les données au pas d’origine (quart d’heure dans les fichiers Groupe E
  testés) ;
- calcule les kWh à partir de `kW × pas de mesure` ;
- signale les valeurs `Manquant`, les trous de mesure, les doublons et le changement
  d’heure ;
- produit les synthèses annuelles et mensuelles, les pics et une comparaison N / N-1
  strictement limitée aux quarts d’heure valides communs ;
- produit quatre journées types à partir des données réelles :
  printemps, été, automne et hiver ;
- analyse l’import nocturne, l’injection entre 10 h et 16 h, le surplus disponible
  au-dessus de 1 / 2 / 3 / 5 kW, les plages de soutirage récurrentes et un plafond
  théorique de déplacement de charge ;
- génère des recommandations client compréhensibles.

L’application ne calcule **ni la consommation totale du bâtiment ni la production
photovoltaïque totale** avec les seuls flux import/export. Elle ne dimensionne pas
encore une batterie et ne présente donc aucun gain financier de stockage sans
tarifs ni scénario de pilotage.

## Structure

```text
analyse-energie/
├── streamlit_app.py
├── energy_analysis/
│   ├── ingest.py           # lecture Excel, unités, déduplication, qualité
│   ├── metrics.py          # kWh, périodes, profils et comparaison
│   ├── recommendations.py  # règles de conseil explicables
│   ├── charts.py           # figures Plotly
│   └── config.py           # couleurs et seuils visibles
├── tests/
│   └── test_energy_analysis.py
├── .streamlit/config.toml
├── requirements.txt
├── requirements-dev.txt
└── .gitignore
```

## Convention des dates Groupe E

Les deux fichiers validés commencent à `00:15` et se terminent à `00:00` le
lendemain. La valeur est donc interprétée par défaut comme la **fin de
l’intervalle**. Une ligne du `01.01 à 00:00` clôt ainsi le dernier quart d’heure
du 31.12, sans créer une nouvelle année artificielle.

Le choix peut être modifié dans la barre latérale si un autre fournisseur utilise
un horodatage de début d’intervalle.

Les dates Excel ne contiennent pas de fuseau horaire : l’application les traite
comme l’heure locale renseignée par le fournisseur. Elle ne reconstruit jamais
l’heure répétée lors du passage à l’heure d’hiver.

## Lancer localement

Avec Python 3.11 ou ultérieur :

```bash
python -m venv .venv
```

Sous Windows :

```powershell
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
streamlit run streamlit_app.py
```

Sous macOS ou Linux :

```bash
source .venv/bin/activate
pip install -r requirements-dev.txt
streamlit run streamlit_app.py
```

Tests :

```bash
pytest -q
ruff check .
```

## Déploiement GitHub et Streamlit Community Cloud

1. Créez un dépôt GitHub privé, par exemple `soleol/analyse-energie`.
2. Copiez le contenu de ce dossier à la racine du dépôt.
3. Vérifiez que les fichiers clients Excel ne sont pas ajoutés au dépôt :
   `.gitignore` les exclut volontairement.
4. Poussez le dépôt sur GitHub.
5. Dans Streamlit Community Cloud, créez une application, choisissez le dépôt,
   la branche et `streamlit_app.py` comme fichier principal.
6. Déployez. Toute modification validée sur GitHub redéploie l’application.

`requirements.txt` et `.streamlit/config.toml` sont à la racine, ce qui permet un
comportement identique en local et dans Streamlit Community Cloud.

## Évolutions prévues

Le modèle est séparé de Streamlit pour pouvoir ajouter sans réécrire les calculs :

- un scénario de pilotage paramétrable (ECS, PAC, véhicule électrique) ;
- une simulation de batterie au quart d’heure **après** pilotage ;
- tarifs d’achat et de rétribution paramétrables ;
- comparaison avant / après batterie ;
- rapport PDF client avec synthèse, graphiques, recommandations et hypothèses.

Le futur module batterie devra toujours afficher ses hypothèses : capacité utile,
puissance, rendement, SOC, stratégie de charge, tarifs et règle de recharge réseau.
