"""
QUANT / COMPLIANCE - Validation automatique du mandat (PASS / FAIL).

Chaque contrainte du mandat devient un test unitaire objectif :
  { nom, categorie, limite, valeur, statut PASS/FAIL/N-A, detail }

Le verdict est calculé en Python à partir des métriques mesurées - le LLM
ne participe PAS à cette section (auditabilité totale pour le jury).
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Optional


def _norm(s: str) -> str:
    """Normalise un libellé (minuscules, sans accents) pour le matching."""
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower().replace("_", " ").strip()


def _test(nom: str, categorie: str, limite: str, valeur: str,
          ok: Optional[bool], detail: str = "") -> Dict[str, Any]:
    statut = "N/A" if ok is None else ("PASS" if ok else "FAIL")
    return {"nom": nom, "categorie": categorie, "limite": limite,
            "valeur": valeur, "statut": statut, "detail": detail}


def check_mandate_compliance(mandate, portfolio,
                             metrics: Dict[str, Any]) -> Dict[str, Any]:
    """
    Args:
        mandate   : MandateOutput
        portfolio : PortfolioOutput
        metrics   : full_metrics() sur la période complète (source des
                    métriques mesurées : vol, beta, TE, max drawdown)
    """
    tests: List[Dict[str, Any]] = []
    br = mandate.budget_risque

    def pct(x): return f"{x:.1%}" if isinstance(x, (int, float)) else "N/D"
    def num(x): return f"{x:.2f}" if isinstance(x, (int, float)) else "N/D"

    # ── Risque de marché ──────────────────────────────────────────────────────
    vol = metrics.get("volatilite")
    tests.append(_test("Volatilité annualisée", "Risque",
                       f"≤ {pct(br.volatilite_max)}", pct(vol),
                       None if vol is None else vol <= br.volatilite_max))

    te = metrics.get("tracking_error")
    tests.append(_test("Tracking error", "Risque",
                       f"≤ {pct(br.tracking_error_max)}", pct(te),
                       None if te is None else te <= br.tracking_error_max))

    beta = metrics.get("beta")
    tests.append(_test("Beta vs benchmark", "Risque",
                       f"[{br.beta_min:.2f} ; {br.beta_max:.2f}]", num(beta),
                       None if beta is None else br.beta_min <= beta <= br.beta_max))

    mdd = metrics.get("max_drawdown")
    tests.append(_test("Drawdown maximum historique", "Risque",
                       f"≥ -{pct(br.drawdown_max)}", pct(mdd),
                       None if mdd is None else abs(mdd) <= br.drawdown_max,
                       "mesuré sur l'historique complet du backtest"))

    # ── Structure du portefeuille ─────────────────────────────────────────────
    weights = sorted((p.poids for p in portfolio.positions), reverse=True)
    top10 = sum(weights[:10])
    tests.append(_test("Concentration top 10", "Structure",
                       f"≤ {pct(br.concentration_top10_max)}", pct(top10),
                       top10 <= br.concentration_top10_max))

    w_max = max(weights) if weights else 0.0
    heaviest = max(portfolio.positions, key=lambda p: p.poids).ticker if portfolio.positions else ""
    tests.append(_test("Poids maximum par position", "Structure",
                       f"≤ {pct(mandate.poids_max_par_position)}", pct(w_max),
                       w_max <= mandate.poids_max_par_position + 1e-9,
                       f"position la plus lourde : {heaviest}"))

    n = portfolio.nombre_positions or len(portfolio.positions)
    lo, hi = _parse_range(mandate.nombre_positions_cible)
    tests.append(_test("Nombre de positions", "Structure",
                       f"[{lo} ; {hi}]" if lo is not None else "cible non chiffrée",
                       str(n),
                       None if lo is None else lo <= n <= hi))

    cash = portfolio.cash_poids
    tests.append(_test("Liquidités", "Structure",
                       f"[{pct(mandate.cash_min)} ; {pct(mandate.cash_max)}]", pct(cash),
                       mandate.cash_min - 1e-9 <= cash <= mandate.cash_max + 1e-9))

    # ── Contraintes sectorielles ──────────────────────────────────────────────
    exposure = {(_norm(k)): v for k, v in
                portfolio.repartition_sectorielle.model_dump().items()
                if isinstance(v, (int, float))}
    for secteur, c in mandate.contraintes_sectorielles.items():
        expo = exposure.get(_norm(secteur))
        tests.append(_test(f"Secteur {secteur}", "Secteurs",
                           f"[{pct(c.min)} ; {pct(c.max)}]",
                           pct(expo) if expo is not None else "non exposé",
                           None if expo is None
                           else c.min - 1e-9 <= expo <= c.max + 1e-9))

    # ── Contraintes géographiques ─────────────────────────────────────────────
    geo_expo: Dict[str, float] = {}
    for p in portfolio.positions:
        key = _norm(p.geographie) or "inconnu"
        geo_expo[key] = geo_expo.get(key, 0.0) + p.poids
    for zone, c in mandate.contraintes_geographiques.items():
        # matching souple : "amerique du nord" ⊇ "etats-unis"
        zone_n = _norm(zone)
        expo = geo_expo.get(zone_n)
        if expo is None:
            expo = sum(v for k, v in geo_expo.items()
                       if zone_n in k or k in zone_n) or None
        tests.append(_test(f"Zone {zone}", "Géographie",
                           f"[{pct(c.min)} ; {pct(c.max)}]",
                           pct(expo) if expo is not None else "non exposé",
                           None if expo is None
                           else c.min - 1e-9 <= expo <= c.max + 1e-9))

    # ── Exclusions ────────────────────────────────────────────────────────────
    if mandate.actifs_exclus:
        hits = []
        for p in portfolio.positions:
            hay = _norm(f"{p.nom} {p.secteur} {p.role_portefeuille}")
            for excl in mandate.actifs_exclus:
                if _norm(excl) and _norm(excl) in hay:
                    hits.append(f"{p.ticker} ({excl})")
        tests.append(_test("Secteurs / actifs exclus", "ESG & exclusions",
                           ", ".join(mandate.actifs_exclus),
                           "aucune exposition détectée" if not hits else ", ".join(hits),
                           not hits,
                           "vérification lexicale nom/secteur des positions"))

    if mandate.criteres_ESG:
        tests.append(_test("Critères ESG", "ESG & exclusions",
                           str(mandate.criteres_ESG), "déclaratif",
                           None, "non vérifiable sans fournisseur de données ESG - limite documentée"))

    # ── Verdict global ────────────────────────────────────────────────────────
    n_fail = sum(1 for t in tests if t["statut"] == "FAIL")
    n_pass = sum(1 for t in tests if t["statut"] == "PASS")
    return {
        "tests": tests,
        "n_pass": n_pass,
        "n_fail": n_fail,
        "n_na": sum(1 for t in tests if t["statut"] == "N/A"),
        "statut_global": "PASS" if n_fail == 0 else "FAIL",
    }


def _parse_range(target: str):
    """Parse '25-35' → (25, 35). Retourne (None, None) si non chiffré."""
    m = re.findall(r"\d+", target or "")
    if len(m) >= 2:
        return int(m[0]), int(m[1])
    if len(m) == 1:
        v = int(m[0])
        return max(1, v - 5), v + 5
    return None, None
