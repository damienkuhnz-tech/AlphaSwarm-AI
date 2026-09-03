"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  MODELS / PORTFOLIO - SCHÉMA DE SORTIE DU PORTFOLIO CONSTRUCTION (ÉT. 4/8) ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Rôle : représenter le portefeuille construit (positions + cash).           ║
║  Produit par PortfolioConstructionAgent, consommé par :                     ║
║    - RiskManagementAgent (étape 5) pour calculer les métriques de risque    ║
║    - ComplianceAgent (étape 6) pour vérifier les règles du mandat           ║
║    - ExecutionAgent (étape 7) pour préparer les ordres OMS                  ║
║    - SupervisorAgent (étape 8) pour la décision finale                      ║
║    - runner.py pour l'affichage du tableau de portefeuille                  ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

# ── Imports ───────────────────────────────────────────────────────────────────
from pydantic import BaseModel, Field
from typing import List, Optional, Any, Dict


# ── Sous-modèles ──────────────────────────────────────────────────────────────

class Position(BaseModel):
    # Une ligne de portefeuille = un titre avec son poids et sa valeur USD.
    ticker: str
    nom: str = ""
    poids: float = Field(default=0.0, ge=0.0, le=1.0)  # 0.0 à 1.0 (pas de %)
    valeur_usd: float = 0.0       # Valeur en dollars = capital × poids
    secteur: str = ""
    geographie: str = ""
    role_portefeuille: str = ""   # ex: "core growth", "diversification", "hedge"
    justification: str = ""       # Pourquoi ce titre à ce poids


class ProfilAttendu(BaseModel):
    # Profil risque/rendement estimé du portefeuille global.
    # Valeurs en string pour flexibilité (ex: "~12%", "14-16%", "N/D").
    rendement_annualise: str = ""
    volatilite_estimee: str = ""
    tracking_error: str = ""
    beta: str = ""
    sharpe_estime: Optional[str] = None


class RepartitionSectorielle(BaseModel):
    # Somme des poids par secteur. Doit respecter contraintes_sectorielles du mandat.
    # model_config extra="allow" : accepte des secteurs non listés ci-dessous.
    model_config = {"extra": "allow"}

    Technologie: float = 0.0
    Sante: float = 0.0
    Finance: float = 0.0
    Industrie: float = 0.0
    Consommation_courante: float = 0.0
    Consommation_discretionnaire: float = 0.0
    Energie: float = 0.0
    Materiaux: float = 0.0
    Services_publics: float = 0.0
    Immobilier: float = 0.0
    Telecom: float = 0.0
    Autre: float = 0.0


# ── Modèle principal ──────────────────────────────────────────────────────────
# PortfolioOutput est la sortie la plus centrale du workflow.
# C'est elle qui est vérifiée par 4 agents différents.

class PortfolioOutput(BaseModel):

    # ── Positions (liste ordonnée par poids décroissant par convention) ───────
    positions: List[Position] = Field(default_factory=list)

    # ── Cash ──────────────────────────────────────────────────────────────────
    cash_poids: float = 0.05          # Part du cash (5% par défaut)
    cash_valeur_usd: float = 0.0      # Valeur USD du cash

    # ── Agrégats ──────────────────────────────────────────────────────────────
    capital_total: float = 0.0        # Doit correspondre au capital du mandat
    nombre_positions: int = 0         # Recalculé automatiquement si = 0 (post_init)

    # ── Répartition sectorielle (sous-modèle) ─────────────────────────────────
    repartition_sectorielle: RepartitionSectorielle = Field(
        default_factory=RepartitionSectorielle
    )

    # ── Profil risque/rendement (sous-modèle) ─────────────────────────────────
    profil_attendu: ProfilAttendu = Field(default_factory=ProfilAttendu)

    # ── Décisions notables ────────────────────────────────────────────────────
    decisions_notables: List[str] = Field(default_factory=list)
    # Ex: ["Sous-pondération Énergie vs benchmark", "Surpoids Inde (5%)"]

    # ── Métadonnée de boucle ──────────────────────────────────────────────────
    iteration: int = 1
    # Numéro de l'itération courante dans la boucle Portfolio ↔ Risk.
    # Si Risk = AJUSTER, PortfolioAgent retourne une v2, v3...

    # ── Post-init : conversions et calculs automatiques ───────────────────────
    def model_post_init(self, __context: Any) -> None:
        # Problème fréquent : Claude retourne repartition_sectorielle en dict brut.
        # On force la conversion en objet Pydantic ici.
        if isinstance(self.repartition_sectorielle, dict):
            object.__setattr__(
                self, "repartition_sectorielle",
                RepartitionSectorielle(**self.repartition_sectorielle)
            )
        # Même chose pour profil_attendu.
        if isinstance(self.profil_attendu, dict):
            object.__setattr__(
                self, "profil_attendu",
                ProfilAttendu(**self.profil_attendu)
            )
        # Si le LLM n'a pas compté les positions, on le fait automatiquement.
        if self.nombre_positions == 0:
            object.__setattr__(self, "nombre_positions", len(self.positions))
