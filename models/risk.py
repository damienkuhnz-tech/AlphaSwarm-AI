"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  MODELS / RISK - SCHÉMA DE SORTIE DU RISK MANAGEMENT AGENT (ÉTAPE 5/8)     ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Rôle : formaliser le rapport de risque du portefeuille.                    ║
║  Le statut (PASS / AJUSTER / FAIL) pilote la boucle dans workflow.py :      ║
║    PASS    → on continue vers Compliance (étape 6)                          ║
║    AJUSTER → PortfolioAgent retravaille (boucle, max 3 itérations)          ║
║    FAIL    → violation critique, on passe directement au Supervisor         ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

# ── Imports ───────────────────────────────────────────────────────────────────
from pydantic import BaseModel, Field
from typing import List, Literal, Optional


# ── Sous-modèles ──────────────────────────────────────────────────────────────

class MetriquesRisque(BaseModel):
    # Métriques CALCULÉES en Python (compute_portfolio_metrics) puis FORCÉES dans
    # le rapport par le Risk Agent - ce ne sont PAS des estimations du LLM.
    # En string pour uniformité d'affichage (ex: "14.2%", "0.95").
    concentration_top1: str         # Part du titre le plus lourd
    concentration_top5: str         # Part des 5 premières positions
    concentration_top10: str        # Part des 10 premières positions
    volatilite_estimee: str         # Volatilité annualisée du portefeuille
    tracking_error_estimee: str     # Tracking error annualisée vs benchmark
    beta_estime: str                # Beta vs le benchmark du mandat
    exposition_sectorielle: dict    # Répartition par secteur (dict libre)

    # ── Traçabilité (defaults pour rétro-compatibilité) ──────────────────────
    benchmark_utilise: str = ""     # ETF proxy réellement utilisé (ex: "URTH")
    periode: str = ""               # Période du calcul (ex: "3y")


class Backtest(BaseModel):
    # Résultat du backtest rétrospectif (tools/backtest.py). Tous Optional pour
    # rétro-compatibilité : un RiskReport sans backtest reste valide.
    statut: str = "ERREUR"                          # "OK" | "ERREUR"
    rendement_total: Optional[float] = None         # ex: 0.28 → +28%
    rendement_benchmark: Optional[float] = None     # ex: 0.215
    surperformance: Optional[float] = None          # ex: 0.065 → +6.5pts vs bench
    volatilite_realisee: Optional[float] = None     # ex: 0.147
    sharpe: Optional[float] = None                  # ex: 1.91
    max_drawdown: Optional[float] = None            # ex: -0.1215
    courbe_valeur: List[dict] = Field(default_factory=list)  # points base 100
    tickers_exclus: List[str] = Field(default_factory=list)  # sans historique
    jours: Optional[int] = None
    benchmark_utilise: str = ""
    periode: str = ""
    message: str = ""                               # si statut="ERREUR"


class ViolationRisque(BaseModel):
    # Une violation = une contrainte du mandat non respectée.
    type: str       # ex: "CONCENTRATION", "VOLATILITE", "TRACKING_ERROR"
    detail: str     # Description précise de la violation
    action: str     # Action corrective suggérée par le Risk Agent

    # Literal : Pydantic accepte UNIQUEMENT ces 4 valeurs exactes.
    # "INFORMATIVE" est accepté ici (contrairement à une ancienne version),
    # ce qui évite une ValidationError quand Claude utilise ce terme.
    severite: Literal["MINEURE", "MAJEURE", "CRITIQUE", "INFORMATIVE"]


# ── Modèle principal ──────────────────────────────────────────────────────────
# Le statut est la clé de routage du workflow (voir orchestrator/workflow.py).

class RiskReport(BaseModel):

    # ── Verdict global ────────────────────────────────────────────────────────
    statut: Literal["PASS", "FAIL", "AJUSTER"]
    # PASS    : toutes les métriques dans les limites du mandat
    # AJUSTER : violations mineures/majeures → le Portfolio doit être retravaillé
    # FAIL    : violation critique → workflow bloqué, Supervisor alerté

    # ── Métriques détaillées ──────────────────────────────────────────────────
    metriques_risque: MetriquesRisque
    # Calculées via l'outil compute_portfolio_metrics (yfinance + numpy)

    # ── Violations ────────────────────────────────────────────────────────────
    violations: List[ViolationRisque] = Field(default_factory=list)
    # Liste vide si PASS. Chaque violation a une sévérité et une action corrective.

    # ── Recommandations textuelles ────────────────────────────────────────────
    recommandations: List[str] = Field(default_factory=list)
    # Strings simples transmises au PortfolioAgent lors de la boucle d'ajustement.
    # ex: "Réduire exposition Technologie de 32% à 28%"

    # ── Score global ──────────────────────────────────────────────────────────
    score_risque_global: Optional[int] = None
    # Score 0-100 (0 = risque maximal). Optionnel pour ne pas bloquer si absent.

    commentaire: str = ""
    # Commentaire libre du Risk Agent sur la situation globale du portefeuille.

    # ── Backtest rétrospectif (Lot D) ─────────────────────────────────────────
    backtest: Optional[Backtest] = None
    # Performance simulée du portefeuille (poids figés) sur la période écoulée.
    commentaire_backtest: str = ""
    # Interprétation LLM courte du backtest (optionnelle, vide si pas de crédits).

    # ── Validation quantitative complète (moteur quant/, Lot E) ──────────────
    validation_quantitative: Optional[dict] = None
    # Rapport JSON complet produit par quant.run_full_validation() :
    # performance, train/test split, walk-forward, bootstrap, Monte Carlo,
    # stress tests, benchmarks, compliance PASS/FAIL, rolling metrics.
    # Dict libre (déjà validé côté moteur) → consommé tel quel par l'UI.
