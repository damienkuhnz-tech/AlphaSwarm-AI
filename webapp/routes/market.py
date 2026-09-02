"""
WEBAPP / ROUTES / MARKET — cotations de l'onglet Marché.

GET /api/quotes      : quotes enrichies (cache 30 min, yfinance → FMP)
GET /api/quotes/live : prix live fast_info pour l'auto-refresh (~8 s)
"""

from datetime import datetime

from flask import Blueprint, request, jsonify

bp = Blueprint("market", __name__)

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  GET /api/quotes?tickers=NVDA,MSFT,... — COURS DE BOURSE (onglet Marché)   │
# │  Utilise tools.market_data.get_stock_info (cache 30 min, fallback FMP).    │
# │  Renvoie une liste de quotes : prix, capitalisation, beta, 52w range, etc. │
# └─────────────────────────────────────────────────────────────────────────────┘

@bp.route("/api/quotes", methods=["GET"])
def get_quotes():
    """
    Cours de bourse pour un ou plusieurs tickers.
    Query param : ?tickers=NVDA,MSFT,LLY  (séparés par des virgules)
    Données via tools.market_data (yfinance → fallback FMP, cache LRU 30 min).
    """
    import re as _re
    from tools.market_data import get_stock_info, get_price_history

    raw = request.args.get("tickers", "").strip()
    if not raw:
        return jsonify({"error": "Paramètre 'tickers' requis"}), 400

    # Découpe + sanitisation (max 20 tickers par appel pour limiter la charge)
    tickers = [t.strip().upper() for t in raw.split(",") if t.strip()][:20]
    valid = [t for t in tickers if _re.match(r'^[A-Z0-9.\-^]{1,12}$', t)]

    def _clean(x):
        # Neutralise NaN/inf venant de yfinance (sinon JSON invalide / affichage cassé)
        if isinstance(x, float) and (x != x or x in (float("inf"), float("-inf"))):
            return None
        return x

    def _quote_one(tk):
        # Travail complet pour UN ticker (info + historique). Isolé pour être
        # parallélisable : chaque ticker = 2 requêtes réseau indépendantes.
        info = get_stock_info(tk)
        if info.get("statut") != "OK":
            return {
                "ticker":  tk,
                "statut":  "ERREUR",
                "message": info.get("message", "Données indisponibles"),
            }
        # Performance YTD-ish (1 an) via l'historique (déjà caché)
        perf = None
        hist = get_price_history(tk, period="1y")
        if hist.get("statut") == "OK":
            perf = hist.get("performance_periode")
            # yfinance peut renvoyer NaN → casse le JSON. On neutralise en None.
            if perf is not None and perf != perf:  # NaN != NaN
                perf = None
        prix = _clean(info.get("prix_actuel"))
        bas  = _clean(info.get("semaine_52_bas"))
        haut = _clean(info.get("semaine_52_haut"))
        # Position dans la fourchette 52 semaines (0 = au plus bas, 1 = au plus haut)
        pos_52w = None
        if prix and bas and haut and haut > bas:
            pos_52w = round((prix - bas) / (haut - bas), 4)
        return {
            "ticker":          tk,
            "nom":             info.get("nom"),
            "secteur":         info.get("secteur"),
            "pays":            info.get("pays"),
            "devise":          info.get("devise", "USD"),
            "prix":            prix,
            "capitalisation_mrd": _clean(info.get("capitalisation_mrd_usd")),
            "beta":            _clean(info.get("beta")),
            "semaine_52_bas":  bas,
            "semaine_52_haut": haut,
            "position_52w":    pos_52w,
            "volume_moyen_30j": _clean(info.get("volume_moyen_30j")),
            "perf_1an":        perf,
            "source":          info.get("_source", "?"),
            "statut":          "OK",
        }

    # Parallélisation I/O-bound : N tickers = N×2 requêtes réseau. En séquentiel,
    # 5 tickers ≈ 10 s ; avec 8 workers ≈ 1,5 s. L'ordre des résultats est
    # préservé par executor.map. Un ticker en échec n'affecte pas les autres.
    from concurrent.futures import ThreadPoolExecutor
    if len(valid) > 1:
        with ThreadPoolExecutor(max_workers=min(8, len(valid))) as ex:
            quotes = list(ex.map(_quote_one, valid))
    else:
        quotes = [_quote_one(tk) for tk in valid]

    return jsonify({
        "quotes":   quotes,
        "horodatage": datetime.utcnow().isoformat() + "Z",
        "note":     "Données quasi temps réel (cache 30 min, source yfinance/FMP).",
    })


# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  GET /api/quotes/live?tickers=NVDA,MSFT — COURS LIVE (polling rapide)      │
# │  Contourne le cache 30 min. Utilise yf.Ticker.fast_info (endpoint léger    │
# │  Yahoo, conçu pour le prix). Appelé par l'auto-refresh frontend (~8s).     │
# │  Renvoie last_price + previous_close → la variation du jour est calculable.│
# └─────────────────────────────────────────────────────────────────────────────┘

@bp.route("/api/quotes/live", methods=["GET"])
def get_quotes_live():
    """
    Cours LIVE (pas de cache) pour l'auto-refresh de l'onglet Marché.
    fast_info de yfinance = endpoint Yahoo léger, rapide, pensé pour le prix.
    Tolérant aux pannes : un ticker en échec n'invalide pas les autres.
    """
    import re as _re
    import yfinance as yf

    raw = request.args.get("tickers", "").strip()
    if not raw:
        return jsonify({"error": "Paramètre 'tickers' requis"}), 400

    tickers = [t.strip().upper() for t in raw.split(",") if t.strip()][:20]
    valid = [t for t in tickers if _re.match(r'^[A-Z0-9.\-^]{1,12}$', t)]

    def _num(x):
        # NaN/inf/None → None (JSON propre)
        try:
            x = float(x)
        except (TypeError, ValueError):
            return None
        if x != x or x in (float("inf"), float("-inf")):
            return None
        return x

    def _live_one(tk):
        try:
            fi = yf.Ticker(tk).fast_info
            last = _num(fi["last_price"])
            prev = _num(fi["previous_close"])
            if last is None:
                return {"ticker": tk, "statut": "ERREUR", "message": "Prix indisponible"}
            # Variation du jour (vs clôture précédente)
            var_abs = var_pct = None
            if prev not in (None, 0):
                var_abs = round(last - prev, 4)
                var_pct = round((last - prev) / prev, 6)
            return {
                "ticker":         tk,
                "prix":           last,
                "cloture_prec":   prev,
                "variation_abs":  var_abs,
                "variation_pct":  var_pct,
                "ouverture":      _num(fi["open"]),
                "haut_jour":      _num(fi["day_high"]),
                "bas_jour":       _num(fi["day_low"]),
                "annee_haut":     _num(fi["year_high"]),
                "annee_bas":      _num(fi["year_low"]),
                "volume":         _num(fi["last_volume"]),
                "devise":         (fi["currency"] or "USD"),
                "statut":         "OK",
            }
        except Exception as e:
            return {"ticker": tk, "statut": "ERREUR", "message": str(e)[:80]}

    # Endpoint pollé toutes les ~8 s par l'onglet Marché : la latence perçue est
    # celle du ticker le plus lent, pas la somme → parallélisation I/O.
    from concurrent.futures import ThreadPoolExecutor
    if len(valid) > 1:
        with ThreadPoolExecutor(max_workers=min(8, len(valid))) as ex:
            quotes = list(ex.map(_live_one, valid))
    else:
        quotes = [_live_one(tk) for tk in valid]

    return jsonify({
        "quotes":     quotes,
        "horodatage": datetime.utcnow().isoformat() + "Z",
        "note":       "Cours live (fast_info Yahoo, sans cache). Peut être différé selon la place.",
    })
