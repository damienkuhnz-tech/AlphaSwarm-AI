"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  TOOLS / FINANCIAL METRICS - CALCUL DES MÉTRIQUES DE RISQUE PORTEFEUILLE   ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Rôle : calculer les métriques quantitatives de risque d'un portefeuille.  ║
║  Appelé par : RiskManagementAgent via l'outil "compute_portfolio_metrics". ║
║  Le LLM appelle cet outil → on exécute ici → on renvoie les résultats.    ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  IMPORTS                                                                    │
# └─────────────────────────────────────────────────────────────────────────────┘

import pandas as pd
# pd.concat   : aligner les séries temporelles portefeuille et benchmark
# pd.DataFrame: type retourné par yf.download (matrice prix × temps)

import numpy as np
# np.sqrt(252) : annualise la volatilité (252 jours de bourse par an)
# np.cov       : matrice de covariance pour le calcul du beta
# np.array     : vecteur de poids pour la multiplication matricielle

from typing import Dict, List, Any
# Dict : type de retour et des positions
# List : liste des positions [{"ticker": ..., "poids": ...}]
# Any  : type flexible pour les valeurs du dict retourné

import yfinance as yf
# yf.download : télécharge les prix de clôture pour N tickers en un seul appel HTTP


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║  HELPER - MAPPING BENCHMARK DU MANDAT → ETF PROXY YAHOO FINANCE            ║
# ╠═══════════════════════════════════════════════════════════════════════════╣
# ║  Yahoo Finance ne connaît pas les indices "MSCI World" directement.        ║
# ║  On utilise un ETF qui le réplique (URTH pour MSCI World, etc.) afin de    ║
# ║  calculer beta et tracking error CONTRE le benchmark réel du mandat,        ║
# ║  et non un proxy arbitraire. Fallback ACWI (monde entier) si inconnu.       ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

def benchmark_to_etf(benchmark_name: str) -> str:
    """Mappe le libellé du benchmark du mandat vers un ticker ETF/indice Yahoo."""
    name = (benchmark_name or "").lower()
    # Ordre important : les libellés les plus spécifiques d'abord.
    if "acwi" in name or "all country" in name or "all-country" in name:
        return "ACWI"          # iShares MSCI ACWI (monde + émergents)
    if "msci world" in name or ("world" in name and "msci" in name):
        return "URTH"          # iShares MSCI World (marchés développés)
    if "s&p 500" in name or "s&p500" in name or "sp500" in name or "s & p" in name:
        return "^GSPC"         # S&P 500
    if "nasdaq" in name:
        return "^IXIC"         # Nasdaq Composite
    if "euro stoxx 50" in name or "eurostoxx 50" in name or "stoxx 50" in name:
        return "^STOXX50E"     # Euro Stoxx 50
    if "stoxx 600" in name or "stoxx600" in name or "europe 600" in name:
        return "^STOXX"        # Stoxx Europe 600
    if "ftse 100" in name or "ftse100" in name:
        return "^FTSE"         # FTSE 100
    if "cac 40" in name or "cac40" in name:
        return "^FCHI"         # CAC 40
    if "dax" in name:
        return "^GDAXI"        # DAX
    if "nikkei" in name:
        return "^N225"         # Nikkei 225
    if "emerging" in name or "émergent" in name or "emergent" in name:
        return "EEM"           # iShares MSCI Emerging Markets
    if "msci europe" in name or "europe" in name:
        return "IEUR"          # iShares Core MSCI Europe
    return "ACWI"              # Défaut : proxy monde large


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║  FONCTION PRINCIPALE compute_portfolio_metrics()                           ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

def compute_portfolio_metrics(
    positions: List[Dict],
    # Format attendu : [{"ticker": "NVDA", "poids": 0.065}, {"ticker": "MSFT", "poids": 0.07}]
    period: str = "3y",
    # Période d'historique. 3y (≈756 jours) : beta/tracking error nettement plus
    # stables qu'en 1y. La volatilité annualisée reste fiable, et le beta gagne
    # en robustesse statistique (1 an = estimation bruitée du beta).
    benchmark_ticker: str = "ACWI",
    # ETF/indice de référence pour beta et tracking error. Doit être le proxy du
    # benchmark RÉEL du mandat (cf. benchmark_to_etf), pas un proxy arbitraire.
) -> Dict[str, Any]:
    """
    Calcule volatilité, beta, tracking error et corrélations d'un portefeuille,
    sur la période et le benchmark fournis. Toutes les métriques sont des CALCULS
    réels (numpy/pandas sur données yfinance) - aucune estimation.
    """

    # ┌─────────────────────────────────────────────────────────────────────────┐
    # │  BLOC 1 - EXTRACTION DES TICKERS ET POIDS                              │
    # └─────────────────────────────────────────────────────────────────────────┘

    tickers = [p["ticker"] for p in positions]
    # Liste des symboles boursiers. Ex: ["NVDA", "MSFT", "ASML.AS", "7203.T"]

    poids = {p["ticker"]: p["poids"] for p in positions}
    # Dict ticker → poids. Ex: {"NVDA": 0.065, "MSFT": 0.07}
    # Utilisé pour la multiplication matricielle (volatilité portefeuille).

    try:
        # ┌─────────────────────────────────────────────────────────────────────┐
        # │  BLOC 2 - TÉLÉCHARGEMENT DES PRIX (yfinance)                       │
        # └─────────────────────────────────────────────────────────────────────┘

        raw = yf.download(
            tickers,           # Liste de tous les tickers en un seul appel
            period=period,     # "1y" par défaut
            interval="1d",     # Données journalières (252 points/an)
            progress=False,    # Désactive la barre de progression (sortie propre)
            auto_adjust=True   # Ajuste les prix pour les dividendes et splits
        )
        # raw est un DataFrame avec MultiIndex si plusieurs tickers :
        # colonnes = (Open, High, Low, Close, Volume) × ticker
        # Si un ticker est invalide (ex: ^MSCI_WORLD_ETF) → colonne NaN

        # ── Téléchargement du benchmark du MANDAT ────────────────────────────
        # benchmark_ticker = proxy ETF du benchmark réel (URTH pour MSCI World,
        # ^GSPC pour S&P 500, etc.). Calculé en amont via benchmark_to_etf().
        bench_raw = yf.download(
            benchmark_ticker,
            period=period, interval="1d",
            progress=False, auto_adjust=True
        )

        # ┌─────────────────────────────────────────────────────────────────────┐
        # │  BLOC 3 - EXTRACTION DES PRIX DE CLÔTURE                           │
        # └─────────────────────────────────────────────────────────────────────┘

        if "Close" in raw.columns:
            # Un seul ticker → raw["Close"] est une Series, pas un DataFrame.
            # On force en DataFrame pour que les opérations suivantes fonctionnent.
            prices = raw["Close"] if len(tickers) > 1 else raw[["Close"]].rename(columns={"Close": tickers[0]})
        else:
            prices = raw  # Fallback : yfinance retourne parfois sans MultiIndex

        # ── Calcul des rendements journaliers ─────────────────────────────────
        returns = prices.pct_change().dropna()
        # pct_change() : (P_t - P_{t-1}) / P_{t-1} pour chaque jour
        # dropna()     : supprime la 1ère ligne (NaN car pas de P_{t-1})
        # returns est un DataFrame : une colonne par ticker, une ligne par jour

        bench_returns = bench_raw["Close"].pct_change().dropna() if not bench_raw.empty else None
        # Rendements journaliers du benchmark (ACWI)
        # Utilisés pour calculer beta et tracking error

        # ┌─────────────────────────────────────────────────────────────────────┐
        # │  BLOC 4 - VOLATILITÉ INDIVIDUELLE PAR TITRE                        │
        # └─────────────────────────────────────────────────────────────────────┘

        vol_dict = {}
        for t in tickers:
            if t in returns.columns:
                # std() des rendements quotidiens × √252 = volatilité annualisée
                # √252 : facteur d'annualisation (252 jours de bourse par an)
                # Exemple : si std journalier = 1.5%, vol annualisée ≈ 23.8%
                vol_dict[t] = float(returns[t].std() * np.sqrt(252))
        # vol_dict = {"NVDA": 0.45, "MSFT": 0.28, ...} (volatilités annualisées)

        # ┌─────────────────────────────────────────────────────────────────────┐
        # │  BLOC 5 - VOLATILITÉ DU PORTEFEUILLE (approche matricielle)        │
        # └─────────────────────────────────────────────────────────────────────┘

        # ── On ne garde que les tickers avec des données disponibles ──────────
        valid_tickers = [t for t in tickers if t in returns.columns]
        # Exclut les tickers sans données (ex: titres delisted, symboles invalides)

        # ── Vecteur de poids ──────────────────────────────────────────────────
        w = np.array([poids.get(t, 0) for t in valid_tickers])
        # Exemple : [0.07, 0.065, 0.06, ...]
        # poids.get(t, 0) : si un ticker valide n'a pas de poids → 0

        # ── Normalisation des poids ───────────────────────────────────────────
        if w.sum() > 0:
            w = w / w.sum()
        # Nécessaire si certains tickers ont été exclus (données manquantes).
        # La somme des poids doit valoir 1 pour les calculs matriciels.

        # ── Matrice de covariance annualisée ──────────────────────────────────
        cov_matrix = returns[valid_tickers].cov() * 252
        # .cov() : matrice de covariance des rendements journaliers (N×N)
        # × 252  : annualise la covariance (car rendements sont journaliers)
        # Chaque cellule (i,j) = covariance entre le titre i et le titre j

        # ── Variance et volatilité du portefeuille ────────────────────────────
        port_variance = float(w @ cov_matrix.values @ w)
        # @ : multiplication matricielle.
        # Formule : σ²_p = w' × Σ × w
        # w'     : vecteur de poids transposé
        # Σ      : matrice de covariance annualisée
        # w      : vecteur de poids
        # Résultat : variance annualisée du portefeuille (scalaire)

        port_vol = float(np.sqrt(max(port_variance, 0)))
        # max(..., 0) : évite sqrt d'un nombre négatif (arrondi numérique)
        # port_vol : volatilité annualisée du portefeuille. Ex: 0.142 = 14.2%

        # ┌─────────────────────────────────────────────────────────────────────┐
        # │  BLOC 6 - BETA ET TRACKING ERROR vs ACWI                           │
        # └─────────────────────────────────────────────────────────────────────┘

        beta = None  # Initialisés à None : si les données manquent → on renvoie None
        te   = None

        if bench_returns is not None:
            # ── Rendements journaliers du portefeuille ────────────────────────
            port_ret_series = (returns[valid_tickers] * w).sum(axis=1)
            # Pour chaque jour : somme pondérée des rendements individuels
            # Exemple jour J : 0.07 × r_MSFT + 0.065 × r_NVDA + ...

            # ── Alignement sur les mêmes dates ───────────────────────────────
            aligned = pd.concat([port_ret_series, bench_returns], axis=1).dropna()
            # pd.concat sur axis=1 : crée un DataFrame 2 colonnes (portefeuille, benchmark)
            # dropna() : supprime les jours où l'une des deux séries est manquante
            # (marchés fermés différents selon les pays)

            if len(aligned) > 20:
                # Minimum de données pour des statistiques fiables (>20 jours)

                # ── Calcul du Beta ────────────────────────────────────────────
                cov_pb = float(np.cov(aligned.iloc[:, 0], aligned.iloc[:, 1])[0, 1])
                # np.cov retourne une matrice 2×2 :
                # [0,0] = variance du portefeuille
                # [0,1] = covariance(portefeuille, benchmark) ← ce qu'on veut
                # [1,1] = variance du benchmark

                var_b = float(aligned.iloc[:, 1].var())
                # Variance des rendements du benchmark (ACWI)

                beta = round(cov_pb / var_b, 3) if var_b > 0 else None
                # Formule du beta : β = Cov(Rp, Rb) / Var(Rb)
                # beta > 1 : portefeuille plus volatile que le marché
                # beta < 1 : portefeuille moins volatile que le marché
                # beta = 0.95 → pour 1% de hausse du marché, portefeuille gagne 0.95%

                # ── Calcul de la Tracking Error ───────────────────────────────
                diff = aligned.iloc[:, 0] - aligned.iloc[:, 1]
                # Différence journalière entre rendements portefeuille et benchmark

                te = round(float(diff.std() * np.sqrt(252)), 4)
                # std(diff) × √252 = tracking error annualisée
                # Mesure à quel point le portefeuille diverge du benchmark
                # Limite mandat : tracking_error_max = 5% (défaut)

        # ┌─────────────────────────────────────────────────────────────────────┐
        # │  BLOC 7 - CORRÉLATIONS ÉLEVÉES ENTRE PAIRES DE TITRES              │
        # └─────────────────────────────────────────────────────────────────────┘

        corr_matrix = returns[valid_tickers].corr()
        # Matrice de corrélation N×N (valeurs entre -1 et +1)
        # Corrélation = covariance normalisée par les volatilités individuelles

        high_corr = []
        # Détection des paires trop corrélées (> 0.70)
        for i in range(len(valid_tickers)):
            for j in range(i + 1, len(valid_tickers)):
                # i+1 : évite les doublons (paire i/j = paire j/i) et la diagonale (i=i)
                c = corr_matrix.iloc[i, j]
                if c > 0.7:
                    # Seuil 0.70 : au-delà, la diversification est illusoire.
                    # Ex: MSFT/GOOGL souvent > 0.80 → concentrent le risque tech.
                    high_corr.append({
                        "pair":        f"{valid_tickers[i]}/{valid_tickers[j]}",
                        "correlation": round(c, 3),
                    })
        # Ex: [{"pair": "MSFT/NVDA", "correlation": 0.82}, ...]

        # ┌─────────────────────────────────────────────────────────────────────┐
        # │  BLOC 7bis - CONCENTRATIONS top1 / top5 / top10                    │
        # │  Calculées en Python à partir des poids fournis (pas par le LLM).  │
        # └─────────────────────────────────────────────────────────────────────┘
        poids_tries = sorted((p["poids"] for p in positions), reverse=True)
        conc_top1  = round(sum(poids_tries[:1]),  4)
        conc_top5  = round(sum(poids_tries[:5]),  4)
        conc_top10 = round(sum(poids_tries[:10]), 4)

        # ┌─────────────────────────────────────────────────────────────────────┐
        # │  BLOC 8 - RETOUR DES RÉSULTATS                                     │
        # └─────────────────────────────────────────────────────────────────────┘

        return {
            "volatilite_portefeuille": round(port_vol, 4),
            # Ex: 0.1423 → 14.23% de volatilité annualisée

            "volatilite_par_titre": {t: round(v, 4) for t, v in vol_dict.items()},
            # Ex: {"NVDA": 0.4521, "MSFT": 0.2834, ...}

            "beta":            beta,
            # Beta vs le benchmark du mandat. Ex: 0.98 → quasi-neutre. 1.15 → plus risqué.

            "tracking_error":  te,
            # Ex: 0.032 → 3.2% de tracking error annualisée

            "concentration_top1":  conc_top1,   # Ex: 0.082 → la plus grosse ligne pèse 8.2%
            "concentration_top5":  conc_top5,   # Ex: 0.38
            "concentration_top10": conc_top10,  # Ex: 0.55

            "correlations_elevees":    high_corr,
            # Liste des paires > 0.70 → concentration implicite

            "benchmark_utilise": benchmark_ticker,  # Traçabilité : ETF réellement utilisé
            "periode":           period,            # Ex: "3y"

            "statut": "OK",
        }

    except Exception as e:
        # ┌─────────────────────────────────────────────────────────────────────┐
        # │  BLOC 9 - GESTION D'ERREUR (retour dégradé)                        │
        # │  Si yfinance échoue (réseau, ticker invalide, etc.)                │
        # │  Le Risk Agent peut quand même fonctionner avec des données nulles.│
        # └─────────────────────────────────────────────────────────────────────┘
        return {
            "statut":                  "ERREUR",
            "message":                 str(e),
            "volatilite_portefeuille": None,
            "beta":                    None,
            "tracking_error":          None,
            "benchmark_utilise":       benchmark_ticker,
            "periode":                 period,
        }
