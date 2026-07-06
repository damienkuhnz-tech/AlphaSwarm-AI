"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  AGENTS / EXECUTION AGENT — ÉTAPE 5/5                                       ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Rôle : préparer la liste d'ordres pour transmission à l'OMS externe.      ║
║  Input  : portfolio (positions cibles), mandate (contraintes d'exécution)   ║
║  Output : ExecutionOutput (ordres BUY/SELL + coûts + calendrier)            ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  IMPORTANT : AUCUNE EXÉCUTION RÉELLE. Préparation uniquement.               ║
║  Cet agent est SAUTÉ si Compliance=REJETE ou Risk=FAIL (voir workflow.py). ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  IMPORTS                                                                    │
# └─────────────────────────────────────────────────────────────────────────────┘

import json
from typing import Any, Dict
from .base_agent import BaseAgent
from config.prompts import EXECUTION_PROMPT
from models.state import PortfolioState
from models.execution import ExecutionOutput


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║  CLASSE EXECUTIONAGENT                                                      ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

class ExecutionAgent(BaseAgent):
    """
    Prépare les ordres pour export vers l'OMS externe.
    NE FAIT PAS D'EXÉCUTION RÉELLE.
    """

    AGENT_KEY = "execution"
    SYSTEM_PROMPT = EXECUTION_PROMPT
    # Rôle : "trader institutionnel" chargé de structurer les ordres
    # selon les contraintes d'exécution (liquidité, algorithmes, prérequis réglementaires).

    # Pas de TOOLS : les positions cibles et le capital sont connus.
    # L'agent n'a pas besoin de données de marché additionnelles.

    # ┌─────────────────────────────────────────────────────────────────────────┐
    # │  run() — MÉTHODE PRINCIPALE                                             │
    # └─────────────────────────────────────────────────────────────────────────┘

    def run(self, state: PortfolioState) -> Dict[str, Any]:

        # ── BLOC 1 : Lecture des inputs ───────────────────────────────────────
        portfolio = state.get("portfolio")
        # PortfolioOutput : contient les positions avec poids et valeur_usd cibles.
        # Chaque position devient un ordre BUY (portefeuille actuel = VIDE pour 1er run).

        mandate = state.get("mandate")
        # Fournit : liquidite_min_adv_usd pour les contraintes de liquidité.
        # Ex: 5_000_000 USD → un titre avec ADV < 5M ne devrait pas être sélectionné.

        # ── BLOC 2 : Pré-conditions ───────────────────────────────────────────
        if not portfolio or not mandate:
            return {"errors": ["Portfolio ou Mandate manquant"]}

        # ── BLOC 3 : Préparation des positions cibles ─────────────────────────
        # Pour chaque position, on fournit les données nécessaires au LLM
        # pour définir : priorité, algorithme, coûts, prérequis réglementaires.
        positions_cible = json.dumps(
            [
                {
                    "ticker":           p.ticker,       # Ex: "7203.T" (Toyota, marché japonais)
                    "nom":              p.nom,           # Ex: "Toyota Motor Corp"
                    "poids_cible":      p.poids,         # Ex: 0.04 (4% du portefeuille)
                    "valeur_cible_usd": p.valeur_usd,    # Ex: 4_000_000 USD
                    # Le LLM calcule l'algo selon cette valeur (VWAP si >1M USD)
                    "secteur":          p.secteur,       # Info contextuelle pour l'algo
                    "geographie":       p.geographie,    # Détermine les prérequis réglementaires
                    # Ex: "Japon" → prérequis "Compte de trading en JPY requis"
                    # Ex: "Inde"  → prérequis "SEBI registration requise pour marchés INR"
                }
                for p in portfolio.positions
            ],
            ensure_ascii=False, indent=2
        )

        # ── BLOC 4 : Construction du prompt ───────────────────────────────────
        # On précise les règles d'exécution clés que le LLM doit respecter.
        # "PORTEFEUILLE ACTUEL : VIDE" : hypothèse de premier investissement.
        # → ANGLE D'AMÉLIORATION : passer le portefeuille actuel pour calculer
        #   les ordres différentiels (quand le fonds est déjà partiellement investi).
        user_msg = f"""
Prépare la liste d'ordres pour transmission à l'OMS externe.

PORTEFEUILLE ACTUEL : VIDE (premier investissement)

PORTEFEUILLE CIBLE :
{positions_cible}

Cash cible    : {portfolio.cash_poids:.2%} ({portfolio.cash_valeur_usd:,.0f} USD)
Capital total : {portfolio.capital_total:,.0f} USD

CONTRAINTES D'EXÉCUTION :
- Max 10% de l'ADV quotidien par ordre
  → Évite l'impact de marché excessif (déplacement du prix lors de l'achat)
- ADV minimum requis : {mandate.liquidite_min_adv_usd:,.0f} USD
  → Titres sous cette limite = ordres LOW priority
- Algorithmes disponibles : VWAP, TWAP, LIMITE, MARCHÉ
  → VWAP  : pour ordres > 1M USD (exécution étalée dans le temps)
  → TWAP  : pour ordres urgents (exécution linéaire dans le temps)
  → LIMITE : marchés volatils (contrôle du prix d'exécution)
  → MARCHÉ : petits ordres très liquides (exécution immédiate)

Pour chaque ordre :
- Détermine la priorité selon la liquidité du titre (HIGH/NORMAL/LOW)
- Suggère l'algorithme adapté au montant et à la liquidité
- Identifie les prérequis réglementaires (marchés non-US, etc.)
- Estime les coûts (commissions ~10bps, impact marché ~5-10bps)

Retourne UNIQUEMENT le JSON correspondant au schéma ExecutionOutput.
"""
        # ── BLOC 5 : Appel LLM, parsing, validation ───────────────────────────
        raw       = self._call_llm_with_retry(user_msg)
        data      = self._parse_json(raw)
        execution = ExecutionOutput(**data)
        # ExecutionOutput valide :
        #   - Order.action ∈ Literal["BUY","SELL"]
        #   - Order.priorite ∈ Literal["HIGH","NORMAL","LOW"]
        #   - CoutsTransaction avec tous les champs float obligatoires

        # ── BLOC 6 : Retour dans le state ─────────────────────────────────────
        return {
            "execution_output": execution,
            # Consommé par SupervisorAgent (résumé coûts) et runner.py (tableau + export)

            "current_step": "supervisor",
            # Dernière étape avant la validation humaine
        }
