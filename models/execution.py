"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  MODELS / EXECUTION — SCHÉMA DE SORTIE DE L'EXECUTION AGENT (ÉTAPE 7/8)    ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Rôle : formaliser le plan d'exécution des ordres (AUCUNE exécution réelle).║
║  Produit par ExecutionAgent, affiché dans runner.py et exporté en JSON.     ║
║  Le fichier JSON exporté est transmis manuellement à l'OMS externe.         ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

# ── Imports ───────────────────────────────────────────────────────────────────
from pydantic import BaseModel, Field
from typing import List, Literal, Optional


# ── Sous-modèles ──────────────────────────────────────────────────────────────

class Order(BaseModel):
    # Un ordre = instruction d'achat ou de vente d'un titre.
    ticker: str
    action: Literal["BUY", "SELL"]   # Long-only → majority of BUY orders

    # ── Montants ──────────────────────────────────────────────────────────────
    valeur_usd: float     # Montant en USD à investir/désinvestir
    poids_cible: float    # Poids final souhaité dans le portefeuille

    # ── Paramètres d'exécution ────────────────────────────────────────────────
    priorite: Literal["HIGH", "NORMAL", "LOW"]
    # HIGH   : titres très liquides → exécuter en premier
    # NORMAL : exécution standard
    # LOW    : titres peu liquides → fractionner sur plusieurs jours

    algo_suggere: str
    # VWAP  : Volume Weighted Average Price (ordres > 1M USD)
    # TWAP  : Time Weighted Average Price (ordres urgents)
    # LIMITE : ordre à cours limité (marchés volatils)
    # MARCHÉ : ordre au marché (petits ordres très liquides)

    notes_execution: str = ""
    # Instructions spécifiques (ex: "fractionner sur 3 jours", "post-bourse")

    prerequis_reglementaire: Optional[str] = None
    # ex: "KID PRIIP requis avant achat (marché EU)", "Déclaration AMF"


class CoutsTransaction(BaseModel):
    # Estimation des coûts de transaction totaux.
    # Pas de frais réels — estimation par l'agent (~10bps commissions + impact).
    commissions_estimees_usd: float
    market_impact_estime_usd: float  # Impact de marché = prix décalé par l'ordre
    total_estime_usd: float          # commissions + market impact
    total_bps: float                 # Total en points de base vs capital (1bp = 0.01%)


# ── Modèle principal ──────────────────────────────────────────────────────────

class ExecutionOutput(BaseModel):

    # ── Liste des ordres ──────────────────────────────────────────────────────
    ordres: List[Order]
    # Triés par priorité dans runner.py pour l'affichage.

    # ── Résumé financier ──────────────────────────────────────────────────────
    capital_investi: float   # Total USD investi en positions
    capital_cash: float      # Cash résiduel conservé
    capital_total: float     # Doit = capital_investi + capital_cash

    nombre_ordres: int       # Nombre total d'ordres (len(ordres))

    # ── Coûts de transaction ──────────────────────────────────────────────────
    couts_transaction: CoutsTransaction

    # ── Calendrier d'exécution ────────────────────────────────────────────────
    calendrier_suggere: dict = Field(default_factory=dict)
    # ex: {"J+0": ["MSFT", "NVDA"], "J+1": ["SIE.DE", "7203.T"]}

    # ── Statut et avertissement obligatoire ───────────────────────────────────
    statut: str = "EN_ATTENTE_VALIDATION"
    # Rappel légal : AUCUN ordre n'est transmis avant validation humaine explicite.
    avertissement: str = (
        "TOUS LES ORDRES REQUIÈRENT VALIDATION EXPLICITE "
        "DU PORTFOLIO MANAGER AVANT EXPORT VERS L'OMS."
    )
