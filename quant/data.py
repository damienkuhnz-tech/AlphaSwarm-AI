"""
QUANT / DATA — Chargement des prix avec cache disque + mémoire PAR TICKER.

Objectif performance : minimiser les appels réseau.

  - Le cache est PAR TICKER (pas par ensemble de tickers) : quand la boucle
    Portfolio ↔ Risk modifie 3 positions sur 30, seuls les 3 nouveaux tickers
    sont téléchargés — les 27 autres sortent du cache mémoire.
  - Les tickers manquants sont téléchargés en UN SEUL appel batch yfinance.
  - Cache disque (pickle dans .cache/prices/, clé datée) : re-runs le même
    jour → 0 appel réseau. Expiration naturelle chaque jour.

Reproductibilité académique : les prix utilisés par un run peuvent être
rechargés à l'identique depuis le cache disque, ce qui rend les résultats
du mémoire rejouables.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from datetime import date
from pathlib import Path
from typing import Iterable, List

import pandas as pd
import yfinance as yf

logger = logging.getLogger("finagent.quant.data")

# Cache disque à la racine du projet (gitignoré).
CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache" / "prices"

# Cache mémoire process-local : {(ticker, period, date_iso): pd.Series}
_MEMORY_CACHE: dict = {}
_LOCK = threading.Lock()

# Historique par défaut : 10 ans pour couvrir tous les scénarios de stress
# (COVID 2020, inflation 2022, crise bancaire 2023) et un walk-forward
# train 5 ans / test 1 an avec plusieurs fenêtres.
DEFAULT_PERIOD = "10y"


def _key(ticker: str, period: str) -> tuple:
    return (ticker, period, date.today().isoformat())


def _disk_path(ticker: str, period: str) -> Path:
    h = hashlib.sha256(f"{ticker}::{period}::{date.today().isoformat()}".encode()).hexdigest()[:20]
    return CACHE_DIR / f"{h}.pkl"


def _purge_stale_cache(max_age_days: int = 7) -> None:
    """
    Supprime les pickles de prix plus vieux que max_age_days.
    La clé de cache intègre la date du jour : les fichiers de la veille ne sont
    plus jamais relus, mais rien ne les effaçait — le dossier grossissait
    indéfiniment (défaut D9). Appelé au plus une fois par téléchargement.
    """
    import time as _time
    try:
        limite = _time.time() - max_age_days * 86400
        for f in CACHE_DIR.glob("*.pkl"):
            try:
                if f.stat().st_mtime < limite:
                    f.unlink()
            except OSError:
                pass
    except Exception:
        logger.debug("Purge du cache disque impossible", exc_info=True)


def load_prices(tickers: Iterable[str], period: str = DEFAULT_PERIOD) -> pd.DataFrame:
    """
    Retourne un DataFrame de prix de clôture ajustés (colonnes = tickers,
    index = dates). Les tickers sans données sont absents des colonnes.

    Cache mémoire → cache disque → téléchargement batch des seuls manquants.
    """
    tickers = sorted({t for t in tickers if t})
    if not tickers:
        return pd.DataFrame()

    series: dict = {}
    missing: List[str] = []

    # 1) Caches mémoire et disque, ticker par ticker
    for t in tickers:
        with _LOCK:
            cached = _MEMORY_CACHE.get(_key(t, period))
        if cached is not None:
            series[t] = cached
            continue
        p = _disk_path(t, period)
        if p.exists():
            try:
                s = pd.read_pickle(p)
                with _LOCK:
                    _MEMORY_CACHE[_key(t, period)] = s
                series[t] = s
                continue
            except Exception:
                p.unlink(missing_ok=True)  # cache corrompu → retélécharge
        missing.append(t)

    # 2) Téléchargement batch des manquants (un seul appel HTTP)
    if missing:
        logger.info("Téléchargement yfinance : %d tickers manquants (%s), période %s",
                    len(missing), ", ".join(missing[:8]) + ("…" if len(missing) > 8 else ""), period)
        raw = yf.download(
            missing, period=period, interval="1d",
            progress=False, auto_adjust=True, group_by="column",
        )
        close = _extract_close(raw, missing)
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _purge_stale_cache()
        for t in missing:
            if t not in close.columns:
                continue
            s = close[t].dropna()
            if s.empty:
                continue  # ticker invalide/delisté : ni caché, ni retourné
            series[t] = s
            with _LOCK:
                _MEMORY_CACHE[_key(t, period)] = s
            try:
                s.to_pickle(_disk_path(t, period))
            except Exception:
                logger.warning("Écriture du cache disque impossible pour %s", t, exc_info=True)

    if not series:
        return pd.DataFrame()
    return pd.DataFrame(series).sort_index()


def _extract_close(raw: pd.DataFrame, tickers: List[str]) -> pd.DataFrame:
    """Normalise la sortie yfinance (MultiIndex ou non) en DataFrame de Close."""
    if raw is None or raw.empty:
        return pd.DataFrame()
    if isinstance(raw.columns, pd.MultiIndex):
        if "Close" in raw.columns.get_level_values(0):
            close = raw["Close"]
        else:  # group_by="ticker" → niveau 0 = ticker
            close = raw.xs("Close", axis=1, level=1)
    else:
        # Un seul ticker → colonnes plates
        close = raw[["Close"]].rename(columns={"Close": tickers[0]})
    return close


def clear_memory_cache() -> None:
    """Vide le cache mémoire (utile pour les tests)."""
    with _LOCK:
        _MEMORY_CACHE.clear()
