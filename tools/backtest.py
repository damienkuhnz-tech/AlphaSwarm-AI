"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  TOOLS / BACKTEST - PERFORMANCE RÉTROSPECTIVE DU PORTEFEUILLE                ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Rôle : mesurer comment le portefeuille CONSTRUIT aurait performé sur la     ║
║  période écoulée (poids figés appliqués au passé), vs son benchmark.         ║
║  100% calcul (yfinance + numpy) - aucun LLM, déterministe.                   ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  ⚠️ LIMITE MÉTHODOLOGIQUE (à assumer dans le rapport) :                      ║
║  C'est un backtest de l'ALLOCATION ACTUELLE rejouée sur le passé, à poids    ║
║  CONSTANTS. Ce n'est PAS une stratégie re-décidée dans le temps. Les titres  ║
║  retenus aujourd'hui l'ont été en connaissant (indirectement) leur parcours  ║
║  → biais de sélection rétrospectif. À présenter comme une mesure indicative. ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import pandas as pd
import numpy as np
import yfinance as yf
from typing import Dict, List, Any


def backtest_portfolio(
    positions: List[Dict],
    # [{"ticker": "NVDA", "poids": 0.065}, ...]
    period: str = "1y",
    # Période rétrospective. "1y" = 12 derniers mois (~252 jours de bourse).
    benchmark_ticker: str = "ACWI",
    # ETF proxy du benchmark du mandat (cf. financial_metrics.benchmark_to_etf).
) -> Dict[str, Any]:
    """
    Simule la performance du portefeuille (poids figés) sur la période écoulée
    et la compare au benchmark. Retourne rendement, vol réalisée, Sharpe,
    max drawdown, surperformance et la courbe de valeur (base 100).
    """
    tickers = [p["ticker"] for p in positions]
    poids   = {p["ticker"]: p["poids"] for p in positions}

    try:
        # ── Téléchargement des prix (portefeuille + benchmark) ────────────────
        raw = yf.download(tickers, period=period, interval="1d",
                          progress=False, auto_adjust=True)
        bench_raw = yf.download(benchmark_ticker, period=period, interval="1d",
                               progress=False, auto_adjust=True)

        if "Close" in raw.columns:
            prices = raw["Close"] if len(tickers) > 1 else raw[["Close"]]
        else:
            prices = raw

        returns = prices.pct_change().dropna()
        if bench_raw.empty:
            return _erreur("benchmark indisponible", benchmark_ticker, period)
        bench_returns = bench_raw["Close"].pct_change().dropna()

        # ── Tickers valides + poids renormalisés ──────────────────────────────
        valid = [t for t in tickers if t in returns.columns]
        if not valid:
            return _erreur("aucun ticker valide", benchmark_ticker, period)
        w = np.array([poids.get(t, 0) for t in valid])
        if w.sum() <= 0:
            return _erreur("poids nuls", benchmark_ticker, period)
        w = w / w.sum()
        exclus = [t for t in tickers if t not in valid]

        # ── Rendements quotidiens du portefeuille (poids constants) ───────────
        port_ret = (returns[valid] * w).sum(axis=1)

        # ── Alignement portefeuille / benchmark sur les mêmes dates ───────────
        aligned = pd.concat([port_ret, bench_returns], axis=1).dropna()
        aligned.columns = ["port", "bench"]
        if len(aligned) < 20:
            return _erreur("historique insuffisant", benchmark_ticker, period)

        # ── Courbes de valeur (base 100) ──────────────────────────────────────
        port_curve  = (1 + aligned["port"]).cumprod() * 100
        bench_curve = (1 + aligned["bench"]).cumprod() * 100

        rendement_total     = float(port_curve.iloc[-1] / 100 - 1)
        rendement_benchmark = float(bench_curve.iloc[-1] / 100 - 1)
        surperformance      = rendement_total - rendement_benchmark

        # ── Volatilité réalisée annualisée ────────────────────────────────────
        vol_realisee = float(aligned["port"].std() * np.sqrt(252))

        # ── Sharpe (taux sans risque ≈ 0, simplification documentée) ──────────
        n = len(aligned)
        rendement_annualise = float((1 + rendement_total) ** (252.0 / n) - 1)
        sharpe = round(rendement_annualise / vol_realisee, 3) if vol_realisee > 0 else None

        # ── Max drawdown (pire creux pic-à-creux sur la courbe portefeuille) ──
        running_max = port_curve.cummax()
        drawdowns   = port_curve / running_max - 1
        max_drawdown = float(drawdowns.min())

        # ── Courbe échantillonnée (~40 points) pour l'UI ──────────────────────
        step = max(1, len(aligned) // 40)
        idx  = list(range(0, len(aligned), step))
        if idx[-1] != len(aligned) - 1:
            idx.append(len(aligned) - 1)
        courbe = [
            {
                "i":     k,
                "port":  round(float(port_curve.iloc[k]), 2),
                "bench": round(float(bench_curve.iloc[k]), 2),
            }
            for k in idx
        ]

        return {
            "statut":              "OK",
            "rendement_total":     round(rendement_total, 4),
            "rendement_benchmark": round(rendement_benchmark, 4),
            "surperformance":      round(surperformance, 4),
            "volatilite_realisee": round(vol_realisee, 4),
            "sharpe":              sharpe,
            "max_drawdown":        round(max_drawdown, 4),
            "courbe_valeur":       courbe,
            "tickers_exclus":      exclus,   # titres sans historique sur la période
            "jours":               n,
            "benchmark_utilise":   benchmark_ticker,
            "periode":             period,
        }

    except Exception as e:
        return _erreur(str(e), benchmark_ticker, period)


def _erreur(msg: str, bench: str, period: str) -> Dict[str, Any]:
    """Retour dégradé : l'encart UI affichera 'indisponible' sans casser le run."""
    return {
        "statut":            "ERREUR",
        "message":           msg,
        "benchmark_utilise": bench,
        "periode":           period,
    }
