"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  TOOLS / MARKET DATA — COUCHE D'ACCÈS HYBRIDE YAHOO + FMP                   ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Rôle : récupérer les données boursières avec résilience.                    ║
║                                                                              ║
║  Stratégie hybride :                                                         ║
║    1) Tente yfinance (gratuit, pas de clé)                                  ║
║    2) Si Yahoo échoue (401 Invalid Crumb, empty, exception) → fallback FMP   ║
║    3) Si les deux échouent → retourne erreur explicite (pas de données      ║
║       inventées, le LLM saura ne pas halluciner)                            ║
║                                                                              ║
║  Cache : LRU 30 minutes par ticker → évite de retaper les API en boucle.    ║
║  Yahoo bloque souvent quand on tape trop vite, le cache lisse la charge.    ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Utilisateurs :                                                              ║
║    - EquityResearchAgent : appels directs (pre-fetch avant LLM)              ║
║    - RiskManagementAgent : via tool use                                      ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

# ── Imports ───────────────────────────────────────────────────────────────────
import threading
import time
import yfinance as yf
import pandas as pd
from typing import Dict, Any, Optional

from tools.fmp_data import (
    fmp_stock_info,
    fmp_financials,
    fmp_price_history,
    fmp_annual_financials,
)


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║  CACHE LRU SIMPLE (clé = (function_name, ticker, *args))                   ║
# ║  TTL : 30 minutes. Évite de retaper Yahoo/FMP entre runs.                  ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

_CACHE: Dict[tuple, tuple] = {}  # key → (timestamp, value)
_CACHE_TTL = 30 * 60      # 30 minutes
_CACHE_MAXSIZE = 512      # borne dure : évite la croissance illimitée du process
_CACHE_LOCK = threading.Lock()  # les endpoints /api/quotes sont multi-threads


def _cached(key: tuple, fn, *args, **kwargs):
    """Helper de cache : retourne la valeur cachée si fraîche, sinon recompute."""
    now = time.time()
    with _CACHE_LOCK:
        if key in _CACHE:
            ts, val = _CACHE[key]
            if now - ts < _CACHE_TTL:
                return val
    val = fn(*args, **kwargs)
    # On ne cache QUE les succès (sinon on cache les pannes Yahoo, mauvais)
    if isinstance(val, dict) and val.get("statut") == "OK":
        with _CACHE_LOCK:
            if len(_CACHE) >= _CACHE_MAXSIZE:
                # Éviction des 25 % les plus anciens (approx. LRU, O(n log n)
                # mais n ≤ 512 → négligeable, et rare)
                for k, _ in sorted(_CACHE.items(), key=lambda kv: kv[1][0])[:_CACHE_MAXSIZE // 4]:
                    _CACHE.pop(k, None)
            _CACHE[key] = (now, val)
    return val


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║  HELPERS YFINANCE (peuvent échouer, on capte l'échec proprement)           ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

def _yf_stock_info(ticker: str) -> Dict[str, Any]:
    """Tente yfinance.Ticker.info — peut planter sur 401 Yahoo."""
    try:
        info = yf.Ticker(ticker).info
        if not info or not info.get("longName"):
            # Yahoo renvoie parfois un dict vide ou minimal au lieu d'erreur
            return {"ticker": ticker, "statut": "VIDE"}
        return {
            "ticker":                  ticker,
            "nom":                     info.get("longName", "N/D"),
            "secteur":                 info.get("sector", "N/D"),
            "industrie":               info.get("industry", "N/D"),
            "pays":                    info.get("country", "N/D"),
            "devise":                  info.get("currency", "USD"),
            "capitalisation_mrd_usd":  round(info.get("marketCap", 0) / 1e9, 2),
            "prix_actuel":             info.get("currentPrice") or info.get("regularMarketPrice"),
            "volume_moyen_30j":        info.get("averageVolume", 0),
            "beta":                    info.get("beta"),
            "semaine_52_bas":          info.get("fiftyTwoWeekLow"),
            "semaine_52_haut":         info.get("fiftyTwoWeekHigh"),
            "statut":                  "OK",
            "_source":                 "yfinance",
        }
    except Exception as e:
        return {"ticker": ticker, "statut": "ERREUR", "message": str(e), "_source": "yfinance"}


def _yf_financials(ticker: str) -> Dict[str, Any]:
    """Ratios fondamentaux via yfinance."""
    try:
        info = yf.Ticker(ticker).info
        if not info or not info.get("longName"):
            return {"ticker": ticker, "statut": "VIDE"}
        return {
            "ticker":                        ticker,
            "PER_ttm":                       info.get("trailingPE"),
            "PER_forward":                   info.get("forwardPE"),
            "EV_EBITDA":                     info.get("enterpriseToEbitda"),
            "PB_ratio":                      info.get("priceToBook"),
            "PS_ratio":                      info.get("priceToSalesTrailing12Months"),
            "marge_brute":                   info.get("grossMargins"),
            "marge_operationnelle":          info.get("operatingMargins"),
            "marge_nette":                   info.get("profitMargins"),
            "ROE":                           info.get("returnOnEquity"),
            "ROA":                           info.get("returnOnAssets"),
            "croissance_revenus_yoy":        info.get("revenueGrowth"),
            "croissance_benefices_yoy":      info.get("earningsGrowth"),
            "dette_sur_capitaux":            info.get("debtToEquity"),
            "ratio_current":                 info.get("currentRatio"),
            "dividend_yield":                info.get("dividendYield"),
            "eps_ttm":                       info.get("trailingEps"),
            "eps_forward":                   info.get("forwardEps"),
            "statut":                        "OK",
            "_source":                       "yfinance",
        }
    except Exception as e:
        return {"ticker": ticker, "statut": "ERREUR", "message": str(e), "_source": "yfinance"}


def _yf_price_history(ticker: str, period: str = "1y", interval: str = "1d") -> Dict[str, Any]:
    """Historique prix via yfinance."""
    try:
        hist = yf.Ticker(ticker).history(period=period, interval=interval)
        if hist.empty:
            return {"ticker": ticker, "statut": "VIDE"}

        returns     = hist["Close"].pct_change().dropna()
        price_start = float(hist["Close"].iloc[0])
        price_end   = float(hist["Close"].iloc[-1])
        perf        = (price_end - price_start) / price_start

        return {
            "ticker":                ticker,
            "periode":               period,
            "prix_debut":            round(price_start, 2),
            "prix_fin":              round(price_end, 2),
            "performance_periode":   round(perf, 4),
            "volatilite_annualisee": round(float(returns.std()) * (252 ** 0.5), 4),
            "nb_jours":              len(hist),
            "statut":                "OK",
            "_source":               "yfinance",
        }
    except Exception as e:
        return {"ticker": ticker, "statut": "ERREUR", "message": str(e), "_source": "yfinance"}


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║  FONCTIONS PUBLIQUES — FALLBACK YFINANCE → FMP                              ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

def get_stock_info(ticker: str) -> Dict[str, Any]:
    """
    Infos générales d'un titre.
    Stratégie : yfinance d'abord, FMP en fallback si Yahoo plante ou retourne vide.
    """
    return _cached(("info", ticker), _get_stock_info_uncached, ticker)


def _get_stock_info_uncached(ticker: str) -> Dict[str, Any]:
    res = _yf_stock_info(ticker)
    if res.get("statut") == "OK":
        return res
    # Fallback FMP
    res_fmp = fmp_stock_info(ticker)
    if res_fmp.get("statut") == "OK":
        return res_fmp
    # Les deux ont échoué → on retourne le résultat le plus informatif
    return res if res.get("message") else res_fmp


def get_financials(ticker: str) -> Dict[str, Any]:
    """Ratios fondamentaux. Yahoo → FMP fallback."""
    return _cached(("financials", ticker), _get_financials_uncached, ticker)


def _get_financials_uncached(ticker: str) -> Dict[str, Any]:
    res = _yf_financials(ticker)
    if res.get("statut") == "OK":
        return res
    res_fmp = fmp_financials(ticker)
    if res_fmp.get("statut") == "OK":
        return res_fmp
    return res if res.get("message") else res_fmp


def get_price_history(ticker: str, period: str = "1y", interval: str = "1d") -> Dict[str, Any]:
    """Historique de prix + volatilité. Yahoo → FMP fallback."""
    return _cached(("hist", ticker, period, interval),
                   _get_price_history_uncached, ticker, period, interval)


def _get_price_history_uncached(ticker: str, period: str = "1y", interval: str = "1d") -> Dict[str, Any]:
    res = _yf_price_history(ticker, period=period, interval=interval)
    if res.get("statut") == "OK":
        return res
    res_fmp = fmp_price_history(ticker, period=period)
    if res_fmp.get("statut") == "OK":
        return res_fmp
    return res if res.get("message") else res_fmp


# ── Batch d'infos (utilitaire) ────────────────────────────────────────────────

def get_batch_info(tickers: list) -> Dict[str, Dict]:
    """Récupère les infos pour une liste de tickers en batch."""
    return {t: get_stock_info(t) for t in tickers}


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║  FONCTION 5 — FINANCIALS ANNUELS (4 ans d'historique)                      ║
# ║  Yahoo (financials DataFrame) → FMP fallback (income-statement)             ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

def get_annual_financials(ticker: str) -> Dict[str, Any]:
    """Income statement 4 ans + ratios courants. Yahoo → FMP fallback."""
    return _cached(("annual", ticker), _get_annual_financials_uncached, ticker)


def _get_annual_financials_uncached(ticker: str) -> Dict[str, Any]:
    # ── Tentative Yahoo ───────────────────────────────────────────────────────
    try:
        t      = yf.Ticker(ticker)
        info   = t.info
        income = t.financials

        if (income is None or income.empty) and not info.get("longName"):
            raise RuntimeError("Yahoo retourne des données vides")

        result: Dict[str, Any] = {
            "ticker":   ticker,
            "statut":   "OK",
            "annees":   [],
            "_source":  "yfinance",
        }

        if income is not None and not income.empty:
            cols_sorted = sorted(income.columns, reverse=True)[:4]
            for col in cols_sorted:
                year_data: Dict[str, Any] = {
                    "annee": str(col.year) if hasattr(col, "year") else str(col)[:4],
                }
                rev = income.loc["Total Revenue", col] if "Total Revenue" in income.index else None
                year_data["revenue_mio"] = (
                    round(float(rev) / 1e6, 0) if rev is not None and not pd.isna(rev) else None
                )
                ni = income.loc["Net Income", col] if "Net Income" in income.index else None
                year_data["net_income_mio"] = (
                    round(float(ni) / 1e6, 0) if ni is not None and not pd.isna(ni) else None
                )
                ebit = None
                if "EBIT" in income.index:
                    ebit = income.loc["EBIT", col]
                elif "Operating Income" in income.index:
                    ebit = income.loc["Operating Income", col]
                if (
                    ebit is not None and rev is not None
                    and not pd.isna(ebit) and not pd.isna(rev)
                    and float(rev) != 0
                ):
                    year_data["ebit_margin"] = round(float(ebit) / float(rev), 4)
                else:
                    year_data["ebit_margin"] = None
                result["annees"].append(year_data)

        # Enrichissement avec les ratios courants
        result["eps_ttm"]              = info.get("trailingEps")
        result["eps_forward"]          = info.get("forwardEps")
        result["pe_ttm"]               = info.get("trailingPE")
        result["pe_forward"]           = info.get("forwardPE")
        result["roe"]                  = info.get("returnOnEquity")
        result["book_value_per_share"] = info.get("bookValue")
        result["ev_ebitda"]            = info.get("enterpriseToEbitda")
        result["pb_ratio"]             = info.get("priceToBook")

        # Si on a au moins quelques années → succès
        if result["annees"]:
            return result
        raise RuntimeError("Yahoo : aucune donnée annuelle exploitable")

    except Exception:
        # ── Fallback FMP ──────────────────────────────────────────────────────
        return fmp_annual_financials(ticker)


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║  FONCTION 6 — SÉRIES DE PRIX NORMALISÉES (graphique Share Performance)     ║
# ║  Yahoo only pour l'instant (FMP n'a pas la même structure de séries)        ║
# ║  Si Yahoo plante → retourne VIDE, le rapport HTML s'adapte (placeholder).   ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

def get_price_series(
    ticker: str, benchmark: str = "^GSPC", period: str = "1y"
) -> Dict[str, Any]:
    """Séries de prix normalisées pour le graphique. Yahoo only — fallback graphique simple."""
    try:
        t_data = yf.download(ticker,    period=period, progress=False)
        b_data = yf.download(benchmark, period=period, progress=False)

        if t_data.empty:
            return {"ticker": ticker, "statut": "VIDE"}

        t_close = t_data["Close"].squeeze().dropna()
        b_close = b_data["Close"].squeeze().dropna() if not b_data.empty else None

        t_norm = (t_close / t_close.iloc[0] * 100).round(2)
        b_norm = (b_close / b_close.iloc[0] * 100).round(2) if b_close is not None and not b_close.empty else None

        series = []
        for date, val in t_norm.items():
            point: Dict[str, Any] = {
                "date": (date.strftime("%Y-%m") if hasattr(date, "strftime") else str(date)[:7]),
                "ticker_val": float(val),
            }
            if b_norm is not None:
                try:
                    point["benchmark_val"] = round(float(b_norm.asof(date)), 2)
                except Exception:
                    point["benchmark_val"] = 100.0
            else:
                point["benchmark_val"] = 100.0
            series.append(point)

        step = max(1, len(series) // 24)
        return {
            "ticker":      ticker,
            "benchmark":   benchmark,
            "periode":     period,
            "series":      series[::step],
            "perf_ticker": round(float(t_norm.iloc[-1]) - 100, 2),
            "statut":      "OK",
        }
    except Exception as e:
        return {"ticker": ticker, "statut": "ERREUR", "message": str(e)}
