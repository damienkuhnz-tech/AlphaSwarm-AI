"""
QUANT / METRICS - Bibliothèque de métriques de performance et de risque.

Fonctions pures : elles prennent des séries de rendements journaliers
(pd.Series alignées) et retournent des floats. Aucune I/O, aucun état.

Conventions :
  - 252 jours de bourse par an (annualisation standard).
  - Taux sans risque paramétrable (défaut 2 % annuel, hypothèse documentée
    dans le mémoire - plus honnête que l'hypothèse 0 % de l'ancien code).
  - VaR/CVaR : quantiles empiriques (aucune hypothèse de normalité →
    capture l'asymétrie et les queues épaisses des rendements réels).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

TRADING_DAYS = 252
RISK_FREE_RATE = 0.02  # annuel


def _rf_daily(rf: float = RISK_FREE_RATE) -> float:
    return (1 + rf) ** (1 / TRADING_DAYS) - 1


# ── Performance ───────────────────────────────────────────────────────────────

def total_return(returns: pd.Series) -> float:
    """Rendement cumulé sur la période."""
    return float((1 + returns).prod() - 1)


def cagr(returns: pd.Series) -> float:
    """Taux de croissance annuel composé."""
    n = len(returns)
    if n == 0:
        return 0.0
    tr = total_return(returns)
    if tr <= -1:
        return -1.0
    return float((1 + tr) ** (TRADING_DAYS / n) - 1)


def annual_volatility(returns: pd.Series) -> float:
    return float(returns.std() * np.sqrt(TRADING_DAYS))


def downside_volatility(returns: pd.Series, mar: float = 0.0) -> float:
    """Volatilité des seuls rendements sous le seuil (semi-déviation annualisée)."""
    downside = returns[returns < mar]
    if len(downside) < 2:
        return 0.0
    return float(np.sqrt((downside**2).mean()) * np.sqrt(TRADING_DAYS))


def sharpe_ratio(returns: pd.Series, rf: float = RISK_FREE_RATE) -> Optional[float]:
    vol = annual_volatility(returns)
    if vol <= 0:
        return None
    return float((cagr(returns) - rf) / vol)


def sortino_ratio(returns: pd.Series, rf: float = RISK_FREE_RATE) -> Optional[float]:
    dvol = downside_volatility(returns, _rf_daily(rf))
    if dvol <= 0:
        return None
    return float((cagr(returns) - rf) / dvol)


def calmar_ratio(returns: pd.Series) -> Optional[float]:
    mdd = abs(max_drawdown(returns))
    if mdd <= 0:
        return None
    return float(cagr(returns) / mdd)


# ── Risque ────────────────────────────────────────────────────────────────────

def drawdown_series(returns: pd.Series) -> pd.Series:
    """Série des drawdowns (valeurs ≤ 0) au fil du temps."""
    curve = (1 + returns).cumprod()
    return curve / curve.cummax() - 1


def max_drawdown(returns: pd.Series) -> float:
    dd = drawdown_series(returns)
    return float(dd.min()) if len(dd) else 0.0


def drawdown_details(returns: pd.Series) -> Dict[str, Any]:
    """Max drawdown + durée (jours de bourse) + temps de récupération."""
    dd = drawdown_series(returns)
    if dd.empty:
        return {"max_drawdown": 0.0, "duree_jours": 0, "recovery_jours": None}
    trough_idx = dd.idxmin()
    trough_pos = dd.index.get_loc(trough_idx)
    # Début du drawdown : dernier point à 0 avant le creux
    before = dd.iloc[:trough_pos + 1]
    zeros = before[before == 0]
    start_pos = before.index.get_loc(zeros.index[-1]) if len(zeros) else 0
    # Récupération : premier retour à 0 après le creux
    after = dd.iloc[trough_pos:]
    recovered = after[after >= 0]
    recovery = int(after.index.get_loc(recovered.index[0])) if len(recovered) else None
    return {
        "max_drawdown": float(dd.min()),
        "duree_jours": int(trough_pos - start_pos),
        "recovery_jours": recovery,
    }


def var_historical(returns: pd.Series, level: float = 0.95) -> float:
    """VaR historique journalière (quantile empirique, valeur négative)."""
    if returns.empty:
        return 0.0
    return float(np.quantile(returns, 1 - level))


def cvar_historical(returns: pd.Series, level: float = 0.95) -> float:
    """Expected shortfall : moyenne des rendements sous la VaR."""
    if returns.empty:
        return 0.0
    var = var_historical(returns, level)
    tail = returns[returns <= var]
    return float(tail.mean()) if len(tail) else var


# ── Métriques relatives au benchmark ─────────────────────────────────────────

def beta(returns: pd.Series, bench: pd.Series) -> Optional[float]:
    if len(returns) < 20:
        return None
    cov = float(np.cov(returns, bench)[0, 1])
    var_b = float(bench.var())
    return cov / var_b if var_b > 0 else None


def alpha_annual(returns: pd.Series, bench: pd.Series,
                 rf: float = RISK_FREE_RATE) -> Optional[float]:
    """Alpha de Jensen annualisé : rp - [rf + β(rb - rf)]."""
    b = beta(returns, bench)
    if b is None:
        return None
    return float(cagr(returns) - (rf + b * (cagr(bench) - rf)))


def tracking_error(returns: pd.Series, bench: pd.Series) -> float:
    return float((returns - bench).std() * np.sqrt(TRADING_DAYS))


def information_ratio(returns: pd.Series, bench: pd.Series) -> Optional[float]:
    te = tracking_error(returns, bench)
    if te <= 0:
        return None
    return float((cagr(returns) - cagr(bench)) / te)


def treynor_ratio(returns: pd.Series, bench: pd.Series,
                  rf: float = RISK_FREE_RATE) -> Optional[float]:
    b = beta(returns, bench)
    if not b:
        return None
    return float((cagr(returns) - rf) / b)


def correlation(returns: pd.Series, bench: pd.Series) -> Optional[float]:
    if len(returns) < 20:
        return None
    return float(returns.corr(bench))


def hit_ratio(returns: pd.Series, bench: pd.Series, freq: str = "ME") -> Optional[float]:
    """Part des mois où le portefeuille bat le benchmark."""
    if len(returns) < 40:
        return None
    p = (1 + returns).resample(freq).prod() - 1
    b = (1 + bench).resample(freq).prod() - 1
    aligned = pd.concat([p, b], axis=1).dropna()
    if len(aligned) < 3:
        return None
    return float((aligned.iloc[:, 0] > aligned.iloc[:, 1]).mean())


# ── Métriques de structure du portefeuille ────────────────────────────────────

def herfindahl_index(weights: np.ndarray) -> float:
    """HHI : somme des poids². 1/N = parfaitement équipondéré."""
    w = np.asarray(weights, dtype=float)
    s = w.sum()
    if s <= 0:
        return 0.0
    w = w / s
    return float((w**2).sum())


def effective_positions(weights: np.ndarray) -> float:
    """Nombre effectif de positions = 1/HHI."""
    hhi = herfindahl_index(weights)
    return float(1 / hhi) if hhi > 0 else 0.0


def diversification_ratio(weights: np.ndarray, returns: pd.DataFrame) -> Optional[float]:
    """
    Ratio de diversification de Choueifaty & Coignard (2008) :
    (Σ w_i σ_i) / σ_portefeuille. > 1 = bénéfice réel de diversification.
    """
    w = np.asarray(weights, dtype=float)
    if returns.shape[1] != len(w) or returns.empty:
        return None
    vols = returns.std().values * np.sqrt(TRADING_DAYS)
    cov = returns.cov().values * TRADING_DAYS
    port_var = float(w @ cov @ w)
    if port_var <= 0:
        return None
    return float((w * vols).sum() / np.sqrt(port_var))


# ── Rolling metrics (pour le dashboard) ───────────────────────────────────────

def rolling_metrics(returns: pd.Series, bench: pd.Series,
                    window: int = 126, points: int = 80) -> Dict[str, list]:
    """
    Rolling Sharpe / Beta / Volatilité (fenêtre glissante ~6 mois),
    échantillonnés à ~`points` valeurs pour l'affichage.
    """
    if len(returns) < window + 10:
        return {"sharpe": [], "beta": [], "volatilite": []}

    mean = returns.rolling(window).mean()
    std = returns.rolling(window).std()
    roll_sharpe = ((mean - _rf_daily()) / std * np.sqrt(TRADING_DAYS)).dropna()
    roll_vol = (std * np.sqrt(TRADING_DAYS)).dropna()
    cov = returns.rolling(window).cov(bench)
    var_b = bench.rolling(window).var()
    roll_beta = (cov / var_b).dropna()

    def sample(series: pd.Series) -> list:
        if series.empty:
            return []
        step = max(1, len(series) // points)
        pts = series.iloc[::step]
        if pts.index[-1] != series.index[-1]:
            pts = pd.concat([pts, series.iloc[[-1]]])
        return [
            {"date": d.strftime("%Y-%m-%d"), "valeur": round(float(v), 4)}
            for d, v in pts.items() if np.isfinite(v)
        ]

    return {
        "sharpe": sample(roll_sharpe),
        "beta": sample(roll_beta),
        "volatilite": sample(roll_vol),
    }


# ── Agrégat standard ──────────────────────────────────────────────────────────

def full_metrics(returns: pd.Series, bench: pd.Series,
                 rf: float = RISK_FREE_RATE) -> Dict[str, Any]:
    """
    Calcule le jeu complet de métriques sur une paire (portefeuille, benchmark)
    alignée. C'est LE dictionnaire standard réutilisé partout (in-sample,
    out-of-sample, walk-forward, stress tests...).
    """
    dd = drawdown_details(returns)
    r = lambda x, n=4: (round(x, n) if isinstance(x, (int, float)) and np.isfinite(x) else None)
    return {
        # Performance
        "rendement_total":    r(total_return(returns)),
        "cagr":               r(cagr(returns)),
        "alpha":              r(alpha_annual(returns, bench)),
        "beta":               r(beta(returns, bench), 3),
        "sharpe":             r(sharpe_ratio(returns, rf), 3),
        "sortino":            r(sortino_ratio(returns, rf), 3),
        "calmar":             r(calmar_ratio(returns), 3),
        "treynor":            r(treynor_ratio(returns, bench, rf), 3),
        "information_ratio":  r(information_ratio(returns, bench), 3),
        # Risque
        "volatilite":         r(annual_volatility(returns)),
        "volatilite_baisse":  r(downside_volatility(returns)),
        "max_drawdown":       r(dd["max_drawdown"]),
        "drawdown_duree":     dd["duree_jours"],
        "drawdown_recovery":  dd["recovery_jours"],
        "var_95":             r(var_historical(returns, 0.95)),
        "var_99":             r(var_historical(returns, 0.99)),
        "cvar_95":            r(cvar_historical(returns, 0.95)),
        "tracking_error":     r(tracking_error(returns, bench)),
        "correlation":        r(correlation(returns, bench), 3),
        # Relatif
        "rendement_benchmark": r(total_return(bench)),
        "cagr_benchmark":      r(cagr(bench)),
        "surperformance":      r(total_return(returns) - total_return(bench)),
        "hit_ratio":           r(hit_ratio(returns, bench), 3),
        # Contexte
        "jours": int(len(returns)),
        "debut": returns.index[0].strftime("%Y-%m-%d") if len(returns) else None,
        "fin":   returns.index[-1].strftime("%Y-%m-%d") if len(returns) else None,
    }
