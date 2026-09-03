"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  MODELS / MANDATE - SCHÉMA DE SORTIE DU MANDATE AGENT (ÉTAPE 1/8)          ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Rôle : définir la structure du mandat d'investissement.                    ║
║  Le MandateAgent demande au LLM de produire un JSON conforme à ce schéma.  ║
║  Tous les agents suivants lisent mandate pour connaître les contraintes.    ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

# ── Imports ───────────────────────────────────────────────────────────────────
from pydantic import BaseModel, Field, field_validator
from typing import Any, Dict, List


# ── Sous-modèles ──────────────────────────────────────────────────────────────
# Chaque modèle imbriqué représente une contrainte structurée.
# Pydantic valide les types au moment de la construction - si le LLM
# retourne un mauvais type, une ValidationError est levée immédiatement.

class ContrainteSectorielle(BaseModel):
    # Plage d'exposition autorisée pour un secteur donné (ex: Technologie 5-30%)
    # Defaults pour robustesse : le LLM peut ajouter des clés non-conformes
    # (ex: _regles_transversales) qui n'ont pas min/max.
    model_config = {"extra": "allow"}
    max: float = 1.0   # Poids maximum en pourcentage (ex: 0.30 = 30%)
    min: float = 0.0   # Poids minimum en pourcentage (ex: 0.05 = 5%)


class ContrainteGeographique(BaseModel):
    # Plage d'exposition autorisée pour une zone géographique
    model_config = {"extra": "allow"}
    max: float = 1.0   # ex: 0.65 pour Amérique du Nord
    min: float = 0.0   # ex: 0.30 (oblige une diversification minimum)


class BudgetRisque(BaseModel):
    # Enveloppe de risque quantitative du mandat.
    # Utilisée par RiskManagementAgent pour valider les métriques du portefeuille.
    tracking_error_max: float = 0.05       # Écart vs benchmark max autorisé (5%)
    volatilite_max: float = 0.18           # Volatilité annualisée max (18%)
    drawdown_max: float = 0.20             # Drawdown maximum toléré (-20%)
    beta_min: float = 0.80                 # Beta minimum vs benchmark
    beta_max: float = 1.20                 # Beta maximum vs benchmark
    concentration_top10_max: float = 0.55  # Les 10 premières positions max 55%


# ── Modèle principal ──────────────────────────────────────────────────────────
# MandateOutput est le contrat formel entre le Portfolio Manager et AlphaSwarm.
# Il formalise les règles qui gouvernent TOUTES les décisions suivantes.

class MandateOutput(BaseModel):

    # ── Paramètres de base (fournis par main.py) ──────────────────────────────
    strategie: str    # ex: "long-only equity global diversifié"
    benchmark: str    # ex: "MSCI World"
    horizon: str      # ex: "3-5 ans"
    capital: float    # ex: 100_000_000 (USD)

    profil_risque: str = "equilibre"
    # Profil de risque transmis depuis le state (form utilisateur).
    # Valeurs : "conservateur", "modere", "equilibre", "dynamique", "agressif"
    # Pilote le budget_risque et les contraintes sectorielles choisies par le LLM.
    # Défaut "equilibre" pour rétrocompatibilité avec les runs sans form.

    # ── Univers d'investissement ──────────────────────────────────────────────
    # Liste des marchés couverts. Définie par le LLM selon la stratégie.
    univers: List[str]

    # ── Contraintes de position ───────────────────────────────────────────────
    # Field(default=...) permet à Pydantic d'utiliser une valeur par défaut
    # si le LLM ne retourne pas ce champ.
    poids_max_par_position: float = Field(default=0.07)   # Max 7% par titre
    poids_min_par_position: float = Field(default=0.01)   # Min 1% par titre
    nombre_positions_cible: str = "25-35"                  # Nombre de lignes cible

    # ── Contraintes structurelles ─────────────────────────────────────────────
    # Dict[str, ...] : le LLM nomme les secteurs/zones en clé libre.
    # default_factory=dict : si absent, crée un dict vide (pas de contrainte).
    contraintes_sectorielles:  Dict[str, ContrainteSectorielle] = Field(default_factory=dict)
    contraintes_geographiques: Dict[str, ContrainteGeographique] = Field(default_factory=dict)

    # ── Nettoyage des contraintes avant validation ────────────────────────────
    # Le LLM glisse parfois dans ces dicts des clés "transversales" dont la
    # valeur est un scalaire (ex: "_contrainte_minimum_secteurs_distincts": 4 ou
    # "_contrainte_transversale_secondaires_total": 0.3) au lieu d'un objet
    # {min, max}. Pydantic ne peut pas convertir un float/int en ContrainteXxx
    # → ValidationError. Le code aval (portfolio/risk agents) accède à v.max et
    # v.min sur CHAQUE valeur, donc on ne peut pas assouplir le type : on écarte
    # simplement les entrées non-objet avant validation. Les vraies contraintes
    # (valeur dict/objet avec min/max) sont conservées intactes.
    @field_validator("contraintes_sectorielles", "contraintes_geographiques", mode="before")
    @classmethod
    def _drop_scalar_constraints(cls, v):
        if not isinstance(v, dict):
            return {}
        return {
            k: val for k, val in v.items()
            if isinstance(val, (dict, BaseModel))
        }

    # ── Filtres ESG et exclusions ─────────────────────────────────────────────
    actifs_exclus: List[str] = Field(default_factory=list)
    # ex: ["tobacco", "weapons", "coal"] - vérifiés par ComplianceAgent

    criteres_ESG: Dict[str, Any] = Field(default_factory=dict)
    # ex: {"score_minimum": "BB"} - vérifiés par ComplianceAgent
    # Any : le LLM peut retourner str, bool, ou dict imbriqué (ex: piliers_minimum)

    # ── Contraintes opérationnelles ───────────────────────────────────────────
    limite_turnover: float = 0.40          # Max 40% du portefeuille modifié par run
    cash_min: float = 0.02                 # Cash minimum = 2% (liquidité de sécurité)
    cash_max: float = 0.10                 # Cash maximum = 10% (pas de sur-liquidité)

    # ── Budget de risque (sous-modèle) ───────────────────────────────────────
    budget_risque: BudgetRisque = Field(default_factory=BudgetRisque)

    # ── Paramètres opérationnels ──────────────────────────────────────────────
    frequence_rebalancement: str = "Trimestriel"
    liquidite_min_adv_usd: float = 5_000_000   # Volume quotidien minimum (ADV)
    # Évite d'investir dans des titres trop peu liquides (risque d'exécution)

    # ── Analyse de cohérence du mandat ────────────────────────────────────────
    # Incohérences détectées entre priorité_principale et contraintes choisies
    # (ex: préservation_capital avec volatilité 20% → incohérent).
    # Rempli par le LLM - liste vide si aucune incohérence.
    alertes_incoherence: List[str] = Field(default_factory=list)

    # Recommandations correctives proposées par l'agent pour aligner les paramètres
    # Ex: "Aligner volatilité_max à 10% pour cohérence avec préservation_capital"
    recommandations_correctives: List[str] = Field(default_factory=list)
