"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  TOOLS / FMP DATA — DONNÉES VIA FINANCIAL MODELING PREP                     ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Rôle : fournir une source alternative à yfinance via les endpoints stable  ║
║  de FMP (financialmodelingprep.com). Utilisé en fallback automatique par    ║
║  market_data.py quand Yahoo Finance bloque les requêtes (401 Invalid Crumb).║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Endpoints utilisés (tous testés, free tier OK) :                           ║
║    /stable/profile?symbol=...               → infos générales                ║
║    /stable/quote?symbol=...                 → prix + market cap              ║
║    /stable/key-metrics-ttm?symbol=...       → ratios fondamentaux            ║
║    /stable/income-statement?symbol=...      → P&L historique 4 ans          ║
║    /stable/historical-price-eod/full        → 5 ans de cotations             ║
║                                                                              ║
║  Free tier : 250 req/jour. Le cache LRU dans market_data.py limite la       ║
║  consommation et permet plusieurs runs sans atteindre la limite.            ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Ces fonctions retournent les MÊMES STRUCTURES que market_data.py pour     ║
║  permettre un fallback transparent. Format unifié pour le LLM.              ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

# ── Imports ───────────────────────────────────────────────────────────────────
import urllib.request
import urllib.parse
import json
import math
from typing import Any, Dict, List, Optional

from config.settings import settings


# ── Helpers ───────────────────────────────────────────────────────────────────

_BASE_URL = "https://financialmodelingprep.com/stable"


def _fmp_get(endpoint: str, **params) -> Optional[Any]:
    """
    Appel HTTP GET vers FMP. Retourne le JSON parsé ou None si erreur.
    Pas de retry automatique — laisse l'appelant décider du fallback.
    """
    if not settings.FMP_API_KEY:
        return None
    params["apikey"] = settings.FMP_API_KEY
    url = f"{_BASE_URL}/{endpoint}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=8) as r:
            return json.loads(r.read())
    except Exception:
        return None


def _to_float(val) -> Optional[float]:
    """Convertit une valeur en float, retourne None si NaN/None/string non numérique."""
    if val is None:
        return None
    try:
        f = float(val)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║  FONCTION 1 — STOCK INFO (équivalent yfinance .info)                        ║
# ║  Combine /profile + /quote pour avoir les mêmes champs que yfinance.        ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

def fmp_stock_info(ticker: str) -> Dict[str, Any]:
    """Infos générales d'un ticker (équivalent get_stock_info via yfinance)."""
    profile = _fmp_get("profile", symbol=ticker)
    quote   = _fmp_get("quote",   symbol=ticker)

    # Si les deux endpoints échouent, on retourne erreur
    if not profile and not quote:
        return {"ticker": ticker, "statut": "ERREUR", "message": "FMP indisponible"}

    p = profile[0] if (profile and isinstance(profile, list)) else {}
    q = quote[0]   if (quote   and isinstance(quote,   list)) else {}

    # Market cap : on prend la plus récente entre les deux
    market_cap = _to_float(q.get("marketCap")) or _to_float(p.get("mktCap")) or 0.0

    return {
        "ticker":                  ticker,
        "nom":                     p.get("companyName") or q.get("name") or "N/D",
        "secteur":                 p.get("sector", "N/D"),
        "industrie":               p.get("industry", "N/D"),
        "pays":                    p.get("country", "N/D"),
        "devise":                  p.get("currency", "USD"),
        "capitalisation_mrd_usd":  round(market_cap / 1e9, 2) if market_cap else 0,
        "prix_actuel":             _to_float(q.get("price")) or _to_float(p.get("price")),
        "volume_moyen_30j":        int(_to_float(p.get("averageVolume") or q.get("avgVolume")) or 0),
        "beta":                    _to_float(p.get("beta")),
        "semaine_52_bas":          _to_float(q.get("yearLow")),
        "semaine_52_haut":         _to_float(q.get("yearHigh")),
        "statut":                  "OK",
        "_source":                 "FMP",
    }


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║  FONCTION 2 — FINANCIALS (ratios fondamentaux)                              ║
# ║  Source : /key-metrics-ttm + /quote                                         ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

def fmp_financials(ticker: str) -> Dict[str, Any]:
    """Ratios fondamentaux (équivalent get_financials via yfinance)."""
    metrics = _fmp_get("key-metrics-ttm",     symbol=ticker)
    quote   = _fmp_get("quote",               symbol=ticker)
    ratios  = _fmp_get("ratios-ttm",          symbol=ticker)

    if not metrics and not ratios:
        return {"ticker": ticker, "statut": "ERREUR", "message": "FMP indisponible"}

    m = metrics[0] if (metrics and isinstance(metrics, list)) else {}
    q = quote[0]   if (quote   and isinstance(quote,   list)) else {}
    r = ratios[0]  if (ratios  and isinstance(ratios,  list)) else {}

    return {
        "ticker":                    ticker,
        "PER_ttm":                   _to_float(q.get("pe")) or _to_float(r.get("priceToEarningsRatioTTM")),
        "PER_forward":               None,  # FMP free tier n'expose pas le forward PE
        "EV_EBITDA":                 _to_float(m.get("evToEBITDATTM")) or _to_float(r.get("evToEBITDATTM")),
        "PB_ratio":                  _to_float(r.get("priceToBookRatioTTM")),
        "PS_ratio":                  _to_float(r.get("priceToSalesRatioTTM")),
        "marge_brute":               _to_float(r.get("grossProfitMarginTTM")),
        "marge_operationnelle":      _to_float(r.get("operatingProfitMarginTTM")),
        "marge_nette":               _to_float(r.get("netProfitMarginTTM")),
        "ROE":                       _to_float(r.get("returnOnEquityTTM")),
        "ROA":                       _to_float(r.get("returnOnAssetsTTM")),
        "croissance_revenus_yoy":    None,  # nécessite income-statement, calc derrière
        "croissance_benefices_yoy":  None,
        "dette_sur_capitaux":        _to_float(r.get("debtToEquityRatioTTM")),
        "ratio_current":             _to_float(r.get("currentRatioTTM")),
        "dividend_yield":            _to_float(r.get("dividendYieldTTM")),
        "eps_ttm":                   _to_float(q.get("eps")),
        "eps_forward":               None,
        "statut":                    "OK",
        "_source":                   "FMP",
    }


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║  FONCTION 3 — HISTORIQUE DE PRIX (performance + volatilité)                 ║
# ║  Source : /historical-price-eod/full (5 ans de cotations)                   ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

def fmp_price_history(ticker: str, period: str = "1y") -> Dict[str, Any]:
    """Historique de prix + volatilité annualisée (équivalent get_price_history)."""
    data = _fmp_get("historical-price-eod/full", symbol=ticker)
    if not data or not isinstance(data, list):
        return {"ticker": ticker, "statut": "ERREUR", "message": "FMP indisponible"}

    # Filtrage selon period (1y = 252 jours bourse, 6mo = 126, etc.)
    days_map = {"1d": 1, "5d": 5, "1mo": 21, "3mo": 63, "6mo": 126,
                "1y": 252, "2y": 504, "5y": 1260}
    n = days_map.get(period, 252)
    # FMP retourne du plus récent au plus ancien — on prend les n premiers
    closes = [_to_float(d.get("close")) for d in data[:n] if _to_float(d.get("close"))]
    if len(closes) < 2:
        return {"ticker": ticker, "statut": "VIDE"}

    # Reverse pour avoir ordre chronologique (anciens → récents)
    closes.reverse()
    price_start = closes[0]
    price_end   = closes[-1]

    # Calcul rendements quotidiens
    returns = []
    for i in range(1, len(closes)):
        if closes[i-1] > 0:
            returns.append((closes[i] - closes[i-1]) / closes[i-1])
    if not returns:
        return {"ticker": ticker, "statut": "VIDE"}

    # Volatilité annualisée : std × √252
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / len(returns)
    std = var ** 0.5
    vol_annual = std * (252 ** 0.5)

    return {
        "ticker":                ticker,
        "periode":               period,
        "prix_debut":            round(price_start, 2),
        "prix_fin":              round(price_end,   2),
        "performance_periode":   round((price_end - price_start) / price_start, 4),
        "volatilite_annualisee": round(vol_annual, 4),
        "nb_jours":              len(closes),
        "statut":                "OK",
        "_source":               "FMP",
    }


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║  FONCTION 4 — INCOME STATEMENT HISTORIQUE                                   ║
# ║  Source : /income-statement (4 ans dispo en free tier)                      ║
# ║  Retourne la même structure que get_annual_financials de yfinance.          ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

def fmp_annual_financials(ticker: str) -> Dict[str, Any]:
    """Income statement 4 ans + ratios (équivalent get_annual_financials)."""
    income = _fmp_get("income-statement", symbol=ticker, limit=4)
    if not income or not isinstance(income, list):
        return {"ticker": ticker, "statut": "ERREUR", "message": "FMP indisponible"}

    # Récupérer aussi ratios pour les champs eps/pe/roe actuels
    metrics = _fmp_get("key-metrics-ttm", symbol=ticker)
    ratios  = _fmp_get("ratios-ttm",      symbol=ticker)
    quote   = _fmp_get("quote",           symbol=ticker)
    m = metrics[0] if (metrics and isinstance(metrics, list)) else {}
    r = ratios[0]  if (ratios  and isinstance(ratios,  list)) else {}
    q = quote[0]   if (quote   and isinstance(quote,   list)) else {}

    annees: List[Dict[str, Any]] = []
    for row in income[:4]:
        revenue = _to_float(row.get("revenue"))
        ni      = _to_float(row.get("netIncome"))
        ebit    = _to_float(row.get("operatingIncome")) or _to_float(row.get("ebit"))
        eps     = _to_float(row.get("eps"))
        gross   = _to_float(row.get("grossProfit"))

        ebit_margin = round(ebit / revenue, 4) if revenue and ebit else None
        marge_brute = round(gross / revenue, 4) if revenue and gross else None

        annees.append({
            "annee":          (row.get("date") or "")[:4],
            "revenue_mio":    round(revenue / 1e6, 0)    if revenue else None,
            "net_income_mio": round(ni / 1e6, 0)         if ni      else None,
            "eps":            round(eps, 2)              if eps     else None,
            "ebit_margin":    ebit_margin,
            "marge_brute":    marge_brute,
        })

    return {
        "ticker":               ticker,
        "statut":               "OK",
        "annees":               annees,
        "eps_ttm":              _to_float(q.get("eps")),
        "eps_forward":          None,
        "pe_ttm":               _to_float(q.get("pe")) or _to_float(r.get("priceToEarningsRatioTTM")),
        "pe_forward":           None,
        "roe":                  _to_float(r.get("returnOnEquityTTM")),
        "book_value_per_share": _to_float(m.get("bookValuePerShareTTM")),
        "ev_ebitda":            _to_float(m.get("evToEBITDATTM")) or _to_float(r.get("evToEBITDATTM")),
        "pb_ratio":             _to_float(r.get("priceToBookRatioTTM")),
        "_source":              "FMP",
    }


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║  COMPATIBILITÉ ASCENDANTE — alias des anciennes fonctions de fmp_data.py    ║
# ║  L'ancienne version utilisait yfinance derrière une façade FMP. On garde   ║
# ║  les noms pour ne pas casser les imports existants ailleurs dans le code.  ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

def get_fmp_historical_financials(ticker: str) -> Dict[str, Any]:
    """Compat : redirige vers fmp_annual_financials (pour ancien code)."""
    out = fmp_annual_financials(ticker)
    return {"statut": out.get("statut"), "annees": out.get("annees", [])}


def get_fmp_historical_ratios(ticker: str) -> Dict[str, Any]:
    """Compat : ROE par année (calculé depuis income+ratios courants)."""
    income = _fmp_get("income-statement", symbol=ticker, limit=5)
    ratios = _fmp_get("ratios-ttm",       symbol=ticker)
    if not income or not isinstance(income, list):
        return {"statut": "VIDE", "message": "Aucune donnée disponible"}

    # On n'a pas le ROE par année en free tier → ROE TTM courant pour toutes les années
    roe_ttm = None
    if ratios and isinstance(ratios, list) and ratios:
        roe_ttm = _to_float(ratios[0].get("returnOnEquityTTM"))

    annees = []
    for row in income[:5]:
        annees.append({
            "annee":          (row.get("date") or "")[:4],
            "pe_ratio":       None,
            "ev_ebitda":      None,
            "roe":            roe_ttm,  # ROE TTM appliqué (approximation)
            "pb_ratio":       None,
            "dividend_yield": None,
        })
    return {"statut": "OK", "annees": annees}


def get_fmp_analyst_targets(ticker: str) -> Dict[str, Any]:
    """Compat : consensus analystes (FMP price-target-consensus)."""
    data = _fmp_get("price-target-consensus", symbol=ticker)
    if not data or not isinstance(data, list) or not data:
        return {"statut": "VIDE", "message": "Aucun consensus disponible"}
    d = data[0]
    return {
        "statut":           "OK",
        "prix_cible_bas":   _to_float(d.get("targetLow")),
        "prix_cible_moyen": _to_float(d.get("targetMedian") or d.get("targetConsensus")),
        "prix_cible_haut":  _to_float(d.get("targetHigh")),
        "nb_analystes":     d.get("numberOfAnalysts"),
    }
