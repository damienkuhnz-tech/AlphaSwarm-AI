"""
QUANT / BENCHMARKS - Comparaison multi-benchmarks.

Le portefeuille est comparé à :
  - le benchmark du mandat (ETF proxy),
  - le S&P 500 et le Nasdaq (références de marché universelles),
  - un portefeuille ÉQUIPONDÉRÉ sur les mêmes titres (l'allocation
    apporte-t-elle quelque chose au-delà de la sélection ?),
  - des portefeuilles ALÉATOIRES sur le même univers (test placebo :
    la performance est-elle distinguable du hasard ? - répond à la
    critique "conclusions trop affirmatives").

Les portefeuilles aléatoires sont seedés → reproductibles.
"""

from __future__ import annotations

from typing import Any, Dict, List

import numpy as np
import pandas as pd

from . import metrics as M
from .engine import align, portfolio_returns

SEED = 123
N_RANDOM = 200  # portefeuilles aléatoires (distribution, pas un seul tirage)

# Benchmarks de marché systématiquement téléchargés avec les prix du run.
MARKET_BENCHMARKS = {"S&P 500": "^GSPC", "Nasdaq": "^IXIC"}


def compare_benchmarks(
    prices: pd.DataFrame,
    weights: Dict[str, float],
    port: pd.Series,
    mandate_bench: pd.Series,
    mandate_bench_name: str,
    mandate_etf: str = "",
) -> Dict[str, Any]:
    """Construit le tableau comparatif complet du dashboard Benchmark."""
    rows: List[Dict[str, Any]] = []

    def row(name: str, bench_rets: pd.Series, kind: str) -> None:
        p, b = align(port, bench_rets)
        if len(p) < 60:
            return
        rows.append({
            "nom": name,
            "type": kind,
            "cagr": round(M.cagr(b), 4),
            "cagr_portefeuille": round(M.cagr(p), 4),
            "surperformance_annuelle": round(M.cagr(p) - M.cagr(b), 4),
            "tracking_error": round(M.tracking_error(p, b), 4),
            "information_ratio": (lambda ir: round(ir, 3) if ir is not None else None)(
                M.information_ratio(p, b)),
            "hit_ratio": (lambda h: round(h, 3) if h is not None else None)(
                M.hit_ratio(p, b)),
            "volatilite": round(M.annual_volatility(b), 4),
            "max_drawdown": round(M.max_drawdown(b), 4),
            "sharpe": (lambda s: round(s, 3) if s is not None else None)(
                M.sharpe_ratio(b)),
        })

    # 1) Benchmark du mandat
    row(mandate_bench_name, mandate_bench, "mandat")

    # 2) Indices de marché (sauf s'ils sont déjà le benchmark du mandat)
    for name, ticker in MARKET_BENCHMARKS.items():
        if ticker != mandate_etf and ticker in prices.columns:
            row(name, prices[ticker].pct_change().dropna(), "marché")

    # 3) Équipondéré sur le même univers
    ew_weights = {t: 1.0 for t in weights}
    ew_port, _ = portfolio_returns(prices, ew_weights, mode="rebalanced")
    row("Équipondéré (mêmes titres)", ew_port, "contrôle")

    # 4) Portefeuilles aléatoires (test placebo)
    random_test = _random_portfolios_test(prices, weights, port)

    return {"comparaisons": rows, "test_aleatoire": random_test}


def _random_portfolios_test(prices: pd.DataFrame, weights: Dict[str, float],
                            port: pd.Series) -> Dict[str, Any]:
    """
    Génère N_RANDOM portefeuilles à poids aléatoires (Dirichlet) sur le même
    univers de titres, et situe le portefeuille réel dans leur distribution
    de Sharpe. Un percentile élevé signifie que l'ALLOCATION (pas seulement
    la sélection de titres) crée de la valeur.
    """
    valid = [t for t in weights if t in prices.columns]
    if len(valid) < 3:
        return {"statut": "INSUFFISANT"}

    rets = prices[valid].ffill(limit=5).dropna().pct_change().dropna()
    if len(rets) < 252:
        return {"statut": "INSUFFISANT"}

    rng = np.random.default_rng(SEED)
    W = rng.dirichlet(np.ones(len(valid)), size=N_RANDOM)      # (N, n_titres)
    sim = rets.values @ W.T                                     # (jours, N)

    years = len(rets) / 252
    tr = np.prod(1 + sim, axis=0) - 1
    cagrs = (1 + tr) ** (1 / years) - 1
    vols = sim.std(axis=0) * np.sqrt(252)
    with np.errstate(divide="ignore", invalid="ignore"):
        sharpes = np.where(vols > 0, (cagrs - M.RISK_FREE_RATE) / vols, np.nan)
    sharpes = sharpes[np.isfinite(sharpes)]

    port_sharpe = M.sharpe_ratio(port.loc[rets.index[0]:])
    if port_sharpe is None or len(sharpes) == 0:
        return {"statut": "INSUFFISANT"}

    return {
        "statut": "OK",
        "n_portefeuilles": int(len(sharpes)),
        "seed": SEED,
        "sharpe_portefeuille": round(float(port_sharpe), 3),
        "sharpe_aleatoire_median": round(float(np.median(sharpes)), 3),
        "sharpe_aleatoire_p95": round(float(np.quantile(sharpes, 0.95)), 3),
        "percentile_portefeuille": round(float((sharpes < port_sharpe).mean()), 3),
    }
