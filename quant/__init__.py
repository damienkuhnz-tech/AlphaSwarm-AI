"""
QUANT — Moteur de validation quantitative de FinAgent.

Package 100 % déterministe (numpy/pandas, aucun LLM) qui produit le rapport
de validation complet d'un portefeuille :

  - data        : chargement des prix avec cache (1 seul download par run)
  - metrics     : bibliothèque de métriques (perf, risque, portefeuille)
  - engine      : construction des séries de rendements et backtest
  - validation  : train/test split, walk-forward, bootstrap, Monte Carlo
  - stress      : stress tests sur scénarios historiques
  - benchmarks  : comparaison S&P 500, Nasdaq, equal-weight, random
  - compliance  : validation PASS/FAIL des contraintes du mandat
  - report      : orchestration → dict JSON-sérialisable complet

Point d'entrée principal :

    from quant import run_full_validation
    rapport = run_full_validation(positions, mandate, portfolio)

Justification académique : ce module répond aux critiques classiques d'un
jury (absence de validation out-of-sample, faible significativité statistique,
absence de benchmark, non-reproductibilité) en séparant strictement le calcul
(Python, reproductible, seedé) du jugement (LLM).
"""

from .report import run_full_validation

__all__ = ["run_full_validation"]
