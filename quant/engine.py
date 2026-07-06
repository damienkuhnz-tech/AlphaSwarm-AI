"""
QUANT / ENGINE — Construction des séries de rendements du portefeuille.

Deux modes de simulation, méthodologiquement distincts :

  - "rebalanced" (défaut) : le portefeuille est ramené aux poids cibles à
    chaque rebalancement (mensuel par défaut). C'est la simulation correcte
    d'une politique d'allocation : entre deux rebalancements les poids
    dérivent avec les prix, puis on réaligne. Le turnover induit est mesuré.

  - "fixed" : poids constants chaque jour (hypothèse de l'ancien code) —
    équivaut à un rebalancement quotidien sans coûts, irréaliste mais utile
    comme borne de comparaison.

Le moteur gère les tickers sans historique (exclus + poids renormalisés,
signalés dans le résultat pour transparence méthodologique).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

REBALANCE_FREQ = "ME"  # mensuel


def portfolio_returns(
    prices: pd.DataFrame,
    weights: Dict[str, float],
    mode: str = "rebalanced",
) -> Tuple[pd.Series, Dict[str, Any]]:
    """
    Calcule la série de rendements journaliers du portefeuille.

    Retourne (série, info) où info documente les tickers exclus, les poids
    effectifs et le turnover annualisé induit par le rebalancement.
    """
    valid = [t for t in weights if t in prices.columns]
    excluded = [t for t in weights if t not in valid]
    if not valid:
        return pd.Series(dtype=float), {"tickers_exclus": excluded, "erreur": "aucun ticker valide"}

    w = np.array([weights[t] for t in valid], dtype=float)
    w = w / w.sum()

    px = prices[valid].dropna(how="all")
    # Forward-fill limité : jours fériés locaux ≠ jours US (max 5 jours)
    px = px.ffill(limit=5).dropna()
    rets = px.pct_change().dropna()

    info: Dict[str, Any] = {
        "tickers_exclus": excluded,
        "poids_effectifs": {t: round(float(x), 4) for t, x in zip(valid, w)},
        "mode": mode,
    }

    if rets.empty:
        return pd.Series(dtype=float), {**info, "erreur": "historique vide"}

    if mode == "fixed":
        port = (rets * w).sum(axis=1)
        info["turnover_annuel"] = None
        return port, info

    # ── Mode rebalanced : simulation jour par jour, vectorisée par blocs ──────
    # Entre deux dates de rebalancement, la valeur de chaque ligne évolue avec
    # son prix ; au rebalancement, on réaligne sur les poids cibles.
    rebal_dates = rets.groupby(pd.Grouper(freq=REBALANCE_FREQ)).tail(1).index
    port_values = []
    turnover_total = 0.0
    current_w = w.copy()
    growth = (1 + rets).values
    dates = rets.index

    rebal_set = set(rebal_dates)
    daily_port = np.empty(len(rets))
    for i in range(len(rets)):
        day_growth = growth[i]
        # Rendement du portefeuille ce jour = somme(w_i * r_i)
        daily_port[i] = float((current_w * (day_growth - 1)).sum())
        # Dérive des poids avec les prix
        new_w = current_w * day_growth
        new_w = new_w / new_w.sum()
        if dates[i] in rebal_set:
            turnover_total += float(np.abs(new_w - w).sum()) / 2
            current_w = w.copy()
        else:
            current_w = new_w

    port = pd.Series(daily_port, index=rets.index)
    years = len(rets) / 252
    info["turnover_annuel"] = round(turnover_total / years, 4) if years > 0 else None
    return port, info


def value_curve(returns: pd.Series, base: float = 100.0) -> pd.Series:
    """Courbe de valeur (base 100)."""
    return (1 + returns).cumprod() * base


def sample_curve(curves: Dict[str, pd.Series], points: int = 120) -> List[dict]:
    """
    Échantillonne plusieurs courbes alignées en ~`points` points datés
    pour l'affichage UI. curves = {"port": série, "bench": série, ...}
    """
    df = pd.DataFrame(curves).dropna()
    if df.empty:
        return []
    step = max(1, len(df) // points)
    idx = list(range(0, len(df), step))
    if idx[-1] != len(df) - 1:
        idx.append(len(df) - 1)
    out = []
    for k in idx:
        row = {"date": df.index[k].strftime("%Y-%m-%d")}
        for col in df.columns:
            row[col] = round(float(df[col].iloc[k]), 2)
        out.append(row)
    return out


def align(port: pd.Series, bench: pd.Series) -> Tuple[pd.Series, pd.Series]:
    """Aligne portefeuille et benchmark sur les dates communes."""
    df = pd.concat([port, bench], axis=1, keys=["p", "b"]).dropna()
    return df["p"], df["b"]
