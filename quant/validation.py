"""
QUANT / VALIDATION - Validation statistique du portefeuille.

Quatre protocoles complémentaires, chacun visant un biais précis :

  1. train_test_split : sépare l'historique 80/20. Les métriques in-sample
     (IS) et out-of-sample (OOS) sont rapportées côte à côte - répond à la
     critique "absence de validation out-of-sample".

  2. walk_forward : fenêtres glissantes train 5 ans / test 1 an. Mesure la
     STABILITÉ des performances dans le temps (un bon résultat sur une seule
     période peut être de la chance ; la moyenne et l'écart-type inter-
     fenêtres quantifient la robustesse).

  3. bootstrap : ré-échantillonnage par blocs (préserve l'autocorrélation
     et la corrélation portefeuille/benchmark) → distribution empirique du
     Sharpe, CAGR, max drawdown, avec intervalles de confiance à 95 %.
     Répond à la critique "faible significativité statistique".

  4. monte_carlo : simulation de trajectoires futures à 1 an par bootstrap
     de blocs → probabilité de perte, VaR simulée, probabilité d'atteindre
     un rendement cible.

Reproductibilité : toutes les simulations sont seedées (SEED = 42).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from . import metrics as M

SEED = 42
BLOCK_SIZE = 21          # blocs d'un mois de bourse (préserve l'autocorrélation)
N_BOOTSTRAP = 1000
N_MONTE_CARLO = 2000
MC_HORIZON = 252         # 1 an


# ── 1. Train / Test split ─────────────────────────────────────────────────────

def train_test_split(port: pd.Series, bench: pd.Series,
                     train_ratio: float = 0.8) -> Dict[str, Any]:
    """
    Coupe chronologiquement l'historique : les premiers 80 % (in-sample,
    période "connue" au moment de la construction) vs les derniers 20 %
    (out-of-sample). Pas de mélange aléatoire : les données financières
    sont temporelles, un split aléatoire créerait une fuite d'information.
    """
    n = len(port)
    if n < 100:
        return {"statut": "INSUFFISANT", "message": f"historique trop court ({n} jours)"}
    cut = int(n * train_ratio)
    return {
        "statut": "OK",
        "train_ratio": train_ratio,
        "date_coupure": port.index[cut].strftime("%Y-%m-%d"),
        "in_sample":     M.full_metrics(port.iloc[:cut], bench.iloc[:cut]),
        "out_of_sample": M.full_metrics(port.iloc[cut:], bench.iloc[cut:]),
    }


# ── 2. Walk-Forward ───────────────────────────────────────────────────────────

def walk_forward(port: pd.Series, bench: pd.Series,
                 train_years: int = 5, test_years: int = 1) -> Dict[str, Any]:
    """
    Fenêtres glissantes : [train 5 ans → test 1 an], avancées d'un an.
    Les poids étant fixés par le mandat (allocation stratégique), le "train"
    sert de période de contexte et chaque fenêtre "test" mesure la performance
    sur une période disjointe - l'agrégat mesure la stabilité temporelle.
    """
    train_days = train_years * 252
    test_days = test_years * 252
    n = len(port)
    if n < train_days + test_days:
        # Historique court → on réduit le train à 3 ans avant d'abandonner
        train_days = 3 * 252
        if n < train_days + test_days:
            return {"statut": "INSUFFISANT",
                    "message": f"historique trop court ({n} j) pour un walk-forward"}
        train_years = 3

    folds = []
    start = 0
    while start + train_days + test_days <= n:
        test_slice = slice(start + train_days, start + train_days + test_days)
        p_test, b_test = port.iloc[test_slice], bench.iloc[test_slice]
        m = M.full_metrics(p_test, b_test)
        folds.append({
            "fenetre": len(folds) + 1,
            "test_debut": m["debut"], "test_fin": m["fin"],
            "cagr": m["cagr"], "sharpe": m["sharpe"],
            "volatilite": m["volatilite"], "max_drawdown": m["max_drawdown"],
            "surperformance": m["surperformance"],
        })
        start += test_days

    if not folds:
        return {"statut": "INSUFFISANT", "message": "aucune fenêtre complète"}

    def agg(key: str) -> Dict[str, Optional[float]]:
        vals = [f[key] for f in folds if f[key] is not None]
        if not vals:
            return {"moyenne": None, "ecart_type": None, "min": None, "max": None}
        return {
            "moyenne":    round(float(np.mean(vals)), 4),
            "ecart_type": round(float(np.std(vals)), 4),
            "min":        round(float(np.min(vals)), 4),
            "max":        round(float(np.max(vals)), 4),
        }

    positives = [f for f in folds if (f["cagr"] or 0) > 0]
    return {
        "statut": "OK",
        "config": {"train_annees": train_years, "test_annees": test_years},
        "nb_fenetres": len(folds),
        "fenetres": folds,
        "cagr": agg("cagr"),
        "sharpe": agg("sharpe"),
        "volatilite": agg("volatilite"),
        "max_drawdown": agg("max_drawdown"),
        "surperformance": agg("surperformance"),
        # Part des fenêtres profitables = indicateur simple de stabilité
        "stabilite": round(len(positives) / len(folds), 3),
    }


# ── Ré-échantillonnage par blocs (commun bootstrap / Monte Carlo) ─────────────

def _block_indices(n_days: int, horizon: int, n_sims: int,
                   rng: np.random.Generator) -> np.ndarray:
    """Matrice (n_sims, horizon) d'indices : blocs contigus de BLOCK_SIZE jours."""
    n_blocks = int(np.ceil(horizon / BLOCK_SIZE))
    starts = rng.integers(0, max(1, n_days - BLOCK_SIZE), size=(n_sims, n_blocks))
    offsets = np.arange(BLOCK_SIZE)
    idx = (starts[:, :, None] + offsets[None, None, :]).reshape(n_sims, -1)
    return idx[:, :horizon]


# ── 3. Bootstrap ──────────────────────────────────────────────────────────────

def bootstrap(port: pd.Series, bench: pd.Series,
              n_sims: int = N_BOOTSTRAP) -> Dict[str, Any]:
    """
    Block bootstrap conjoint (portefeuille + benchmark ré-échantillonnés sur
    les MÊMES blocs → la corrélation croisée est préservée). Produit la
    distribution empirique des métriques clés et la probabilité de battre
    le benchmark.
    """
    n = len(port)
    if n < 252:
        return {"statut": "INSUFFISANT", "message": f"historique trop court ({n} jours)"}

    rng = np.random.default_rng(SEED)
    p = port.values
    b = bench.values
    idx = _block_indices(n, n, n_sims, rng)

    sim_p = p[idx]                      # (n_sims, n)
    sim_b = b[idx]

    years = n / 252
    tr_p = np.prod(1 + sim_p, axis=1) - 1
    tr_b = np.prod(1 + sim_b, axis=1) - 1
    cagr_p = (1 + tr_p) ** (1 / years) - 1
    ann_vol = sim_p.std(axis=1) * np.sqrt(252)
    with np.errstate(divide="ignore", invalid="ignore"):
        sharpe = np.where(ann_vol > 0, (cagr_p - M.RISK_FREE_RATE) / ann_vol, np.nan)

    # Max drawdown vectorisé
    curves = np.cumprod(1 + sim_p, axis=1)
    running_max = np.maximum.accumulate(curves, axis=1)
    mdd = (curves / running_max - 1).min(axis=1)

    def dist(arr: np.ndarray) -> Dict[str, float]:
        arr = arr[np.isfinite(arr)]
        return {
            "moyenne":  round(float(np.mean(arr)), 4),
            "mediane":  round(float(np.median(arr)), 4),
            "ecart_type": round(float(np.std(arr)), 4),
            "ci_bas":   round(float(np.quantile(arr, 0.025)), 4),
            "ci_haut":  round(float(np.quantile(arr, 0.975)), 4),
            # Histogramme 30 classes pour l'UI
            "histogramme": _histogram(arr),
        }

    return {
        "statut": "OK",
        "n_simulations": int(n_sims),
        "methode": f"block bootstrap (blocs {BLOCK_SIZE} j), seed {SEED}",
        "cagr": dist(cagr_p),
        "sharpe": dist(sharpe),
        "max_drawdown": dist(mdd),
        "rendement_total": dist(tr_p),
        "prob_batre_benchmark": round(float((tr_p > tr_b).mean()), 4),
        "prob_cagr_positif": round(float((cagr_p > 0).mean()), 4),
        "prob_sharpe_positif": round(float((sharpe[np.isfinite(sharpe)] > 0).mean()), 4),
    }


def _histogram(arr: np.ndarray, bins: int = 30) -> list:
    counts, edges = np.histogram(arr, bins=bins)
    return [
        {"x": round(float((edges[i] + edges[i + 1]) / 2), 4), "n": int(counts[i])}
        for i in range(len(counts))
    ]


# ── 4. Monte Carlo (trajectoires futures) ─────────────────────────────────────

def monte_carlo(port: pd.Series, n_sims: int = N_MONTE_CARLO,
                horizon: int = MC_HORIZON,
                target_return: float = 0.08) -> Dict[str, Any]:
    """
    Simule `n_sims` trajectoires à `horizon` jours par bootstrap de blocs des
    rendements historiques du portefeuille (non-paramétrique : aucune
    hypothèse de normalité, contrairement à un Monte Carlo gaussien).
    """
    n = len(port)
    if n < 252:
        return {"statut": "INSUFFISANT", "message": f"historique trop court ({n} jours)"}

    rng = np.random.default_rng(SEED + 1)
    idx = _block_indices(n, horizon, n_sims, rng)
    sims = port.values[idx]                       # (n_sims, horizon)
    finals = np.prod(1 + sims, axis=1) - 1        # rendement à 1 an

    # Courbes percentiles pour le fan chart de l'UI
    curves = np.cumprod(1 + sims, axis=1) * 100
    steps = np.linspace(0, horizon - 1, 60).astype(int)
    percentiles = {}
    for q, label in [(5, "p5"), (25, "p25"), (50, "p50"), (75, "p75"), (95, "p95")]:
        percentiles[label] = [round(float(v), 2)
                              for v in np.percentile(curves[:, steps], q, axis=0)]

    return {
        "statut": "OK",
        "n_simulations": int(n_sims),
        "horizon_jours": int(horizon),
        "methode": f"block bootstrap non-paramétrique, seed {SEED + 1}",
        "rendement_attendu": round(float(np.mean(finals)), 4),
        "rendement_median": round(float(np.median(finals)), 4),
        "prob_perte": round(float((finals < 0).mean()), 4),
        "prob_perte_10pct": round(float((finals < -0.10).mean()), 4),
        "var_95_1an": round(float(np.quantile(finals, 0.05)), 4),
        "var_99_1an": round(float(np.quantile(finals, 0.01)), 4),
        "cvar_95_1an": round(float(finals[finals <= np.quantile(finals, 0.05)].mean()), 4),
        "rendement_cible": target_return,
        "prob_rendement_cible": round(float((finals >= target_return).mean()), 4),
        "histogramme": _histogram(finals),
        "fan_chart": {"steps": [int(s) for s in steps], **percentiles},
    }
