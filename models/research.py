"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  MODELS / RESEARCH - SCHÉMA DE SORTIE DE L'EQUITY RESEARCH AGENT (ÉT. 3/8) ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Rôle : représenter l'analyse complète d'un titre.                          ║
║  Produit par EquityResearchAgent, consommé par PortfolioConstructionAgent.  ║
║  À ce stade : données réelles yfinance + analyse narrative Claude.          ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

# ── Imports ───────────────────────────────────────────────────────────────────
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any


# ── Sous-modèle ───────────────────────────────────────────────────────────────

class Valorisation(BaseModel):
    # Analyse de la valorisation boursière du titre.
    # Toutes les valeurs sont des strings (flexibilité : "N/D", "35x", "~15%")
    methode_principale: str = ""            # ex: "DCF", "PE relatif", "EV/EBITDA"
    PER_estime_NTM: Optional[str] = None    # PER sur les 12 prochains mois
    EV_EBITDA_NTM: Optional[str] = None     # Multiple EV/EBITDA NTM
    upside_potentiel: Optional[str] = None  # ex: "+25%" ou "faible"
    commentaire_valorisation: str = ""      # Justification textuelle


# ── ResearchOutput ────────────────────────────────────────════════════════════
# C'est l'analyse la plus riche du workflow.
# Elle combine : données marchés réelles (yfinance) + intelligence du LLM.
# Le PortfolioAgent reçoit l'univers COMPLET (BUY/HOLD/SELL) et utilise notamment :
# ticker, nom, score_conviction, recommandation (signal), poids_suggere_initial,
# valorisation (upside/méthode), risques_cles, catalyseurs, these_investissement.
# Les champs lourds (donnees_marche) restent pour les rapports HTML uniquement.

class ResearchOutput(BaseModel):

    # ── Identifiant ───────────────────────────────────────────────────────────
    ticker: str
    nom: str = ""

    # ── Risque systématique ───────────────────────────────────────────────────
    beta: Optional[float] = None
    # Beta du titre (depuis les données marché yfinance). None si indisponible.
    # Utilisé pour la cohérence sélection/risque (biais beta selon profil mandat)
    # et lisible par RiskManagementAgent et les rapports. Rétro-compatible.

    # ── Analyse qualitative (générée par Claude) ──────────────────────────────
    executive_summary: str = ""      # 5 lignes : reco + upside + raisons clés + risque principal
    these_investissement: str = ""   # Résumé 1 phrase de la thèse

    # ── Valorisation (sous-modèle) ────────────────────────────────────────────
    valorisation: Valorisation = Field(default_factory=Valorisation)

    # ── Risques et catalyseurs ────────────────────────────────────────────────
    risques_cles: List[str] = Field(default_factory=list)
    # ex: ["risque réglementaire", "ralentissement IA", "concurrence chinoise"]

    catalyseurs: List[str] = Field(default_factory=list)
    # ex: ["lancement H200", "expansion Inde", "résultats Q2 supérieurs"]

    # ── Scoring ───────────────────────────────────────────────────────────────
    score_conviction: int = Field(default=50, ge=0, le=100)
    # Score 0-100 attribué par Claude. Utilisé par PortfolioAgent pour pondérer.

    recommandation: str = "HOLD"
    # BUY / HOLD / SELL. Seuls les BUY sont transmis au PortfolioAgent.

    poids_suggere_initial: float = Field(default=0.03, ge=0.0, le=0.10)
    # Suggestion de poids (3% par défaut). Le PortfolioAgent peut ajuster.

    # ── Données de marché brutes ──────────────────────────────────────────────
    donnees_marche: Dict[str, Any] = Field(default_factory=dict)
    # Stockage optionnel des données yfinance brutes (non utilisé en downstream)

    # ── Méthode post-init ─────────────────────────────────────────────────────
    def model_post_init(self, __context: Any) -> None:
        # Pydantic appelle cette méthode après __init__.
        # Problème : Claude retourne parfois valorisation en dict Python brut
        # au lieu d'un objet Valorisation → on force la conversion ici.
        if isinstance(self.valorisation, dict):
            object.__setattr__(self, "valorisation", Valorisation(**self.valorisation))
