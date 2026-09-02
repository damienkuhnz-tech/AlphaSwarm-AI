"""
WEBAPP / ROUTES / SECTOR — segmentation sectorielle temps réel du formulaire.

POST /api/sector-segmentation : primary/secondary/excluded selon le profil.
"""

from flask import Blueprint, request, jsonify

bp = Blueprint("sector", __name__)

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  POST /api/sector-segmentation — SEGMENTATION SECTORIELLE EN TEMPS RÉEL   │
# │  Retourne la segmentation sectorielle selon le profil de risque.           │
# │  Appelé pendant que le PM remplit le formulaire (pas besoin de run).      │
# └─────────────────────────────────────────────────────────────────────────────┘

@bp.route("/api/sector-segmentation", methods=["POST"])
def sector_segmentation():
    """
    Retourne la segmentation sectorielle pour un profil donné.
    Utilisé par l'interface pour afficher la segmentation EN TEMPS RÉEL
    pendant que l'utilisateur remplit le formulaire.
    Body JSON : {profil_risque: "conservateur"|...}
    """
    # ── Import retardé (lazy) ─────────────────────────────────────────────────
    # tools/sector_beta.py est lourd à importer — on ne le charge que si la route est appelée
    from tools.sector_beta import (
        get_sector_classification,  # Retourne primary/secondary/excluded pour un profil
        build_sector_weights,       # Retourne les poids min/max par secteur
        GICS_SECTOR_BETA,           # Dict des betas min/max/med par secteur GICS
        RISK_PROFILE_BETA,          # Dict des paramètres beta par profil de risque
    )

    data   = request.get_json(force=True) or {}
    profil = data.get("profil_risque", "equilibre")

    # ── Calcul de la segmentation ─────────────────────────────────────────────
    classif = get_sector_classification(profil)
    # classif = {"primary": ["Technology", ...], "secondary": [...], "excluded": [...]}

    weights = build_sector_weights(profil)
    # weights = {"Technology": {"min": 0.10, "max": 0.35}, ...}

    profile = RISK_PROFILE_BETA.get(profil, RISK_PROFILE_BETA["equilibre"])
    # profile = {"beta_cible_portefeuille": 1.05, "min_secteurs": 5, "description": "..."}

    # ── Construction de la réponse ────────────────────────────────────────────
    # Les trois listes (primary, secondary, excluded) permettent à l'interface
    # d'afficher un tableau sectoriel avec codes couleurs.
    return jsonify({
        "profil":       profil,
        "beta_cible":   profile["beta_cible_portefeuille"],
        "min_secteurs": profile["min_secteurs"],
        "description":  profile["description"],
        "primary": [
            # Secteurs prioritaires : surpondération possible selon le profil
            {
                "secteur":     s,
                "beta_min":    GICS_SECTOR_BETA[s]["beta_min"],
                "beta_max":    GICS_SECTOR_BETA[s]["beta_max"],
                "beta_med":    GICS_SECTOR_BETA[s]["beta_med"],
                "type":        GICS_SECTOR_BETA[s]["type"],        # "cyclique", "defensif", etc.
                "description": GICS_SECTOR_BETA[s]["description"],
                "max_pct":     round(weights[s]["max"] * 100),     # Ex: 35 (%)
                "min_pct":     round(weights[s]["min"] * 100),     # Ex: 10 (%)
            }
            for s in classif["primary"]
        ],
        "secondary": [
            # Secteurs secondaires : exposition limitée autorisée
            {
                "secteur":     s,
                "beta_min":    GICS_SECTOR_BETA[s]["beta_min"],
                "beta_max":    GICS_SECTOR_BETA[s]["beta_max"],
                "beta_med":    GICS_SECTOR_BETA[s]["beta_med"],
                "type":        GICS_SECTOR_BETA[s]["type"],
                "description": GICS_SECTOR_BETA[s]["description"],
                "max_pct":     round(weights[s]["max"] * 100),
                "min_pct":     0,  # Pas de minimum obligatoire pour les secteurs secondaires
            }
            for s in classif["secondary"]
        ],
        "excluded": [
            # Secteurs exclus : pas d'exposition pour ce profil
            {
                "secteur":     s,
                "beta_min":    GICS_SECTOR_BETA[s]["beta_min"],
                "beta_max":    GICS_SECTOR_BETA[s]["beta_max"],
                "beta_med":    GICS_SECTOR_BETA[s]["beta_med"],
                "type":        GICS_SECTOR_BETA[s]["type"],
                "description": GICS_SECTOR_BETA[s]["description"],
                "max_pct":     0,  # Aucune exposition autorisée
                "min_pct":     0,
            }
            for s in classif["excluded"]
        ],
    })
