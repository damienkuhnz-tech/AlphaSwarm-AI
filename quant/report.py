"""
QUANT / REPORT - Orchestration de la validation quantitative complète.

Point d'entrée unique appelé par le RiskManagementAgent :

    rapport = run_full_validation(positions, mandate, portfolio)

Séquence (une seule descente réseau, tout le reste est du calcul local) :

  1. Téléchargement batch : titres + benchmark mandat + S&P 500 + Nasdaq (10 ans, caché)
  2. Série de rendements du portefeuille (rebalancement mensuel)
  3. Performance globale + rolling metrics + courbe de drawdown
  4. Train/Test split 80/20 (in-sample vs out-of-sample)
  5. Walk-forward (train 5 ans / test 1 an)
  6. Bootstrap 1000 simulations (IC 95 %, prob. de battre le benchmark)
  7. Monte Carlo 2000 trajectoires à 1 an (prob. de perte, VaR simulée)
  8. Stress tests historiques (COVID, inflation 2022, crise bancaire 2023...)
  9. Comparaison multi-benchmarks + test placebo (portefeuilles aléatoires)
 10. Compliance du mandat (PASS/FAIL par contrainte)

Le résultat est un dict JSON-sérialisable, prêt pour l'UI et le RiskReport.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, Dict, List

import numpy as np

from . import metrics as M
from .benchmarks import MARKET_BENCHMARKS, compare_benchmarks
from .compliance import check_mandate_compliance
from .data import DEFAULT_PERIOD, load_prices
from .engine import align, portfolio_returns, sample_curve, value_curve
from .stress import stress_tests
from .validation import bootstrap, monte_carlo, train_test_split, walk_forward

logger = logging.getLogger("finagent.quant.report")


def run_full_validation(
    positions: List[Dict[str, Any]],
    mandate,
    portfolio,
    benchmark_etf: str = "ACWI",
    benchmark_name: str = "",
    period: str = DEFAULT_PERIOD,
) -> Dict[str, Any]:
    """
    Args:
        positions     : [{"ticker": str, "poids": float}, ...]
        mandate       : MandateOutput (contraintes)
        portfolio     : PortfolioOutput (structure)
        benchmark_etf : ticker proxy du benchmark du mandat
    """
    t0 = time.time()
    weights = {p["ticker"]: float(p["poids"]) for p in positions if p.get("poids", 0) > 0}

    try:
        # ── 1. Données (un seul appel réseau, caché) ──────────────────────────
        all_tickers = list(weights) + [benchmark_etf] + list(MARKET_BENCHMARKS.values())
        prices = load_prices(all_tickers, period=period)
        if prices.empty or benchmark_etf not in prices.columns:
            return _error("données de marché indisponibles", benchmark_etf)

        bench_prices = prices[benchmark_etf].dropna()
        asset_prices = prices[[t for t in weights if t in prices.columns]]

        # ── 2. Série du portefeuille ──────────────────────────────────────────
        port_raw, info = portfolio_returns(asset_prices, weights, mode="rebalanced")
        if port_raw.empty:
            return _error(info.get("erreur", "série portefeuille vide"), benchmark_etf)
        bench_rets = bench_prices.pct_change().dropna()
        port, bench = align(port_raw, bench_rets)
        if len(port) < 252:
            return _error(f"historique commun insuffisant ({len(port)} jours)", benchmark_etf)

        # ── 3. Performance globale ────────────────────────────────────────────
        perf = M.full_metrics(port, bench)
        curves = sample_curve({
            "port": value_curve(port),
            "bench": value_curve(bench),
        })
        dd_series = M.drawdown_series(port)
        dd_curve = sample_curve({"drawdown": dd_series * 100})

        # ── Structure du portefeuille ─────────────────────────────────────────
        w_arr = np.array([info["poids_effectifs"][t]
                          for t in asset_prices.columns if t in info["poids_effectifs"]])
        valid_rets = asset_prices.ffill(limit=5).dropna().pct_change().dropna()
        structure = {
            "nombre_positions": len(weights),
            "herfindahl": round(M.herfindahl_index(w_arr), 4),
            "positions_effectives": round(M.effective_positions(w_arr), 1),
            "ratio_diversification": (lambda d: round(d, 3) if d else None)(
                M.diversification_ratio(
                    np.array([info["poids_effectifs"].get(t, 0) for t in valid_rets.columns]),
                    valid_rets)),
            "turnover_annuel_rebalancement": info.get("turnover_annuel"),
            "tickers_exclus": info.get("tickers_exclus", []),
            "exposition_sectorielle": {
                k: v for k, v in portfolio.repartition_sectorielle.model_dump().items()
                if isinstance(v, (int, float)) and v > 0
            },
            "exposition_geographique": _geo_exposure(portfolio),
        }

        # ── 4-7. Protocoles de validation statistique ─────────────────────────
        split = train_test_split(port, bench)
        wf = walk_forward(port, bench)
        boot = bootstrap(port, bench)
        mc = monte_carlo(port)

        # ── 8. Stress tests ───────────────────────────────────────────────────
        stress = stress_tests(asset_prices, weights, bench_prices)

        # ── 9. Benchmarks ─────────────────────────────────────────────────────
        benchs = compare_benchmarks(prices, weights, port, bench,
                                    benchmark_name or benchmark_etf,
                                    mandate_etf=benchmark_etf)

        # ── 10. Compliance du mandat ──────────────────────────────────────────
        compliance = check_mandate_compliance(mandate, portfolio, perf)

        # ── Rolling metrics ───────────────────────────────────────────────────
        rolling = M.rolling_metrics(port, bench)

        elapsed = round(time.time() - t0, 1)
        logger.info("Validation quantitative complète en %.1fs", elapsed)

        return {
            "statut": "OK",
            "meta": {
                "date_calcul": datetime.now().isoformat(timespec="seconds"),
                "periode": period,
                "jours": perf["jours"],
                "debut": perf["debut"], "fin": perf["fin"],
                "benchmark": benchmark_name or benchmark_etf,
                "benchmark_etf": benchmark_etf,
                "rebalancement": "mensuel",
                "taux_sans_risque": M.RISK_FREE_RATE,
                "duree_calcul_s": elapsed,
            },
            "performance": perf,
            "courbe_valeur": curves,
            "drawdown": {"courbe": dd_curve,
                         "max": perf["max_drawdown"],
                         "duree_jours": perf["drawdown_duree"],
                         "recovery_jours": perf["drawdown_recovery"]},
            "structure": structure,
            "train_test": split,
            "walk_forward": wf,
            "bootstrap": boot,
            "monte_carlo": mc,
            "stress_tests": stress,
            "benchmarks": benchs,
            "compliance": compliance,
            "rolling": rolling,
        }

    except Exception as e:  # jamais de crash du workflow pour un calcul
        logger.exception("Échec de la validation quantitative")
        return _error(str(e), benchmark_etf)


def _geo_exposure(portfolio) -> Dict[str, float]:
    geo: Dict[str, float] = {}
    for p in portfolio.positions:
        key = p.geographie or "Non renseigné"
        geo[key] = round(geo.get(key, 0.0) + p.poids, 4)
    return dict(sorted(geo.items(), key=lambda kv: -kv[1]))


def _error(message: str, benchmark_etf: str) -> Dict[str, Any]:
    return {"statut": "ERREUR", "message": message, "benchmark_etf": benchmark_etf}
