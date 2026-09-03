"""
WEBAPP / SERVICES / CHAT SERVICE - synthèses partagées mandat / recherche.

Helpers utilisés par /api/chat et /api/portfolio/briefing pour que tous les
chats d'agents connaissent le mandat et la liste BUY sans dupliquer la logique.
"""

def _mandate_summary(mandate: dict) -> dict:
    """
    Construit un résumé COMPLET du mandat pour le prompt système d'un chat.
    `mandate` est le dict sérialisé (tel que renvoyé par _serialize / model_dump).
    On expose tous les champs dont un Portfolio Manager a besoin pour dialoguer
    sans rien redemander : profil, horizon, univers, contraintes, budget risque, ESG.
    """
    if not mandate:
        return {}

    budget = mandate.get("budget_risque") or {}
    contraintes = mandate.get("contraintes_sectorielles") or {}
    # On ne garde que secteur -> max pour rester compact (les clés disent déjà l'univers sectoriel).
    contraintes_compact = {}
    for sect, lim in contraintes.items():
        if isinstance(lim, dict):
            contraintes_compact[sect] = lim.get("max")
        else:
            contraintes_compact[sect] = lim

    return {
        "strategie":              mandate.get("strategie"),
        "benchmark":              mandate.get("benchmark"),
        "horizon":                mandate.get("horizon"),
        "capital":                mandate.get("capital"),
        "profil_risque":          mandate.get("profil_risque_effectif") or mandate.get("profil_risque"),
        "priorite":               mandate.get("priorite_principale"),
        "univers":                mandate.get("univers"),
        "poids_max_par_position": mandate.get("poids_max_par_position"),
        "poids_min_par_position": mandate.get("poids_min_par_position"),
        "nombre_positions_cible": mandate.get("nombre_positions_cible"),
        "cash_min":               mandate.get("cash_min"),
        "cash_max":               mandate.get("cash_max"),
        "limite_turnover":        mandate.get("limite_turnover"),
        "frequence_rebalancement": mandate.get("frequence_rebalancement"),
        "contraintes_sectorielles_max": contraintes_compact,
        "criteres_ESG":           mandate.get("criteres_ESG"),
        "actifs_exclus":          mandate.get("actifs_exclus"),
        "budget_risque": {
            "beta_min":            budget.get("beta_min"),
            "beta_max":            budget.get("beta_max"),
            "volatilite_max":      budget.get("volatilite_max"),
            "tracking_error_max":  budget.get("tracking_error_max"),
            "drawdown_max":        budget.get("drawdown_max"),
        },
    }


def _buy_list(research) -> list:
    """Extrait la liste compacte des titres recommandés BUY depuis la recherche."""
    buy = []
    for r in (research or []):
        if not isinstance(r, dict):
            continue
        if r.get("recommandation") == "BUY":
            buy.append({
                "ticker":  r.get("ticker"),
                "nom":     r.get("nom"),
                "secteur": r.get("secteur"),
                "score":   r.get("score_conviction"),
                "these":   (r.get("these_investissement") or "")[:160],
            })
    return buy
