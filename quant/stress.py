"""
QUANT / STRESS - Stress tests sur scénarios historiques réels.

Méthodologie : on rejoue l'allocation actuelle sur des fenêtres de crise
RÉELLES (pas des chocs synthétiques) et on compare au benchmark du mandat.
C'est la pratique standard des risk managers institutionnels : les crises
historiques capturent les corrélations réelles en période de stress, que
les modèles paramétriques sous-estiment (les corrélations montent vers 1
en crise).

Limite documentée : les titres du portefeuille doivent exister sur la
fenêtre du scénario. Les titres absents sont exclus et les poids
renormalisés ; la couverture est rapportée pour transparence.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd

from . import metrics as M
from .engine import align, portfolio_returns

# Scénarios historiques : (nom, description, début, fin)
SCENARIOS = [
    {
        "nom": "Krach COVID",
        "description": "Effondrement pandémique : -34 % sur le S&P 500 en 23 séances.",
        "debut": "2020-02-19", "fin": "2020-04-30",
    },
    {
        "nom": "Choc inflation / hausse des taux",
        "description": "Resserrement Fed 2022 : +425 bps en 9 mois, compression des valorisations.",
        "debut": "2022-01-03", "fin": "2022-10-14",
    },
    {
        "nom": "Bear market 2022",
        "description": "Année baissière complète actions + obligations.",
        "debut": "2022-01-03", "fin": "2022-12-30",
    },
    {
        "nom": "Crise bancaire 2023",
        "description": "Faillites SVB / Signature, rachat Credit Suisse.",
        "debut": "2023-03-01", "fin": "2023-05-01",
    },
    {
        "nom": "Bull market 2023-2024",
        "description": "Rebond IA / désinflation : participation à la hausse.",
        "debut": "2023-01-03", "fin": "2024-12-31",
    },
]


def stress_tests(prices: pd.DataFrame, weights: Dict[str, float],
                 bench_prices: pd.Series) -> List[Dict[str, Any]]:
    """
    Rejoue le portefeuille sur chaque scénario. Retourne une liste de
    résultats (un par scénario), avec statut INDISPONIBLE si l'historique
    ne couvre pas la fenêtre.
    """
    results = []
    bench_rets_full = bench_prices.pct_change().dropna()

    for sc in SCENARIOS:
        window = prices.loc[sc["debut"]:sc["fin"]]
        entry: Dict[str, Any] = {
            "nom": sc["nom"],
            "description": sc["description"],
            "debut": sc["debut"], "fin": sc["fin"],
        }
        if len(window) < 15:
            entry["statut"] = "INDISPONIBLE"
            entry["message"] = "historique insuffisant sur la fenêtre"
            results.append(entry)
            continue

        # Couverture : titres disposant de données sur la fenêtre
        available = [t for t in weights if t in window.columns
                     and window[t].notna().sum() > 10]
        coverage = sum(weights[t] for t in available)
        port, info = portfolio_returns(window, {t: weights[t] for t in available},
                                       mode="rebalanced")
        bench = bench_rets_full.loc[sc["debut"]:sc["fin"]]
        p, b = align(port, bench)
        if len(p) < 15:
            entry["statut"] = "INDISPONIBLE"
            entry["message"] = "alignement portefeuille/benchmark impossible"
            results.append(entry)
            continue

        dd = M.drawdown_details(p)
        entry.update({
            "statut": "OK",
            "couverture_poids": round(float(coverage), 3),
            "tickers_exclus": info.get("tickers_exclus", []),
            "rendement": round(M.total_return(p), 4),
            "rendement_benchmark": round(M.total_return(b), 4),
            "surperformance": round(M.total_return(p) - M.total_return(b), 4),
            "max_drawdown": round(dd["max_drawdown"], 4),
            "max_drawdown_benchmark": round(M.max_drawdown(b), 4),
            "recovery_jours": dd["recovery_jours"],
            "volatilite": round(M.annual_volatility(p), 4),
        })
        results.append(entry)

    return results
