"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  MODELS / STATE - ÉTAT PARTAGÉ ENTRE TOUS LES AGENTS                        ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Rôle : définir la structure du "bus de données" central du workflow.       ║
║  Chaque agent lit ce dont il a besoin et écrit son output dans ce dict.     ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Pourquoi TypedDict et pas Pydantic ?                                       ║
║    TypedDict reste un dict Python standard → le merge {**state, **updates}  ║
║    dans workflow.py fonctionne sans sérialisation/désérialisation.          ║
║    Pydantic serait trop lourd pour un objet qui est constamment mergé.      ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  IMPORTS                                                                    │
# └─────────────────────────────────────────────────────────────────────────────┘

from typing import TypedDict, Optional, List
# TypedDict : dict Python avec des clés typées (pas de validation runtime)
# Optional  : clé peut valoir None (la majorité des clés avant que l'agent tourne)
# List      : pour les champs multi-éléments (ideas, research, errors)

# ── Imports de tous les modèles Pydantic ──────────────────────────────────────
# Chaque modèle correspond à l'output d'un agent spécifique.
# Ces imports permettent de typer précisément chaque clé du state.
from .mandate    import MandateOutput     # Output de MandateAgent (étape 1)
from .research   import ResearchOutput    # Output de EquityResearchAgent (étape 2)
from .portfolio  import PortfolioOutput   # Output de PortfolioConstructionAgent (étape 3)
from .risk       import RiskReport        # Output de RiskManagementAgent (étape 4)
from .execution  import ExecutionOutput   # Output de ExecutionAgent (étape 5)


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║  PORTFOLIOSTATE                                                             ║
# ║  Le dict central partagé entre tous les agents.                            ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

class PortfolioState(TypedDict, total=False):
    # total=False : TOUTES les clés sont optionnelles.
    # Raison : au démarrage, seules les 4 clés d'input existent.
    # Les outputs des agents s'ajoutent progressivement.
    # Sans total=False, Python exigerait toutes les clés dès la création du dict.

    # ┌─────────────────────────────────────────────────────────────────────────┐
    # │  SECTION 1 - INPUTS DU PORTFOLIO MANAGER                               │
    # │  Fournis par main.py via argparse. Immuables durant le workflow.       │
    # └─────────────────────────────────────────────────────────────────────────┘

    strategie: str
    # Texte libre décrivant la stratégie. Ex: "long-only equity global diversifié"
    # Lu par : MandateAgent

    capital: float
    # Montant en USD géré. Ex: 100_000_000 (100 millions).
    # Lu par : MandateAgent (pour définir liquidite_min),
    #          PortfolioConstructionAgent (pour calculer valeur_usd des positions)

    benchmark: str
    # Indice de référence. Ex: "MSCI World"
    # Lu par : MandateAgent, EquityResearchAgent

    horizon: str
    # Durée d'investissement. Ex: "3-5 ans"
    # Lu par : MandateAgent, EquityResearchAgent

    profil_risque: str
    # Profil de tolérance au risque du client.
    # Valeurs : "conservateur", "modere", "equilibre", "dynamique", "agressif"
    # Lu par : MandateAgent (budget risque adaptatif), EquityResearchAgent
    # Défaut : "equilibre" si non fourni

    perte_max_toleree: Optional[float]
    # Perte maximale tolérée sur 12 mois en pourcentage. Ex: 15.0 = -15%
    # Lu par : MandateAgent (renforce le drawdown_max si plus conservateur)

    beta_min_override: Optional[float]
    # Beta minimum explicitement saisi dans le formulaire (champ m-beta-min).
    # Si fourni et incompatible avec profil_risque, le MandateAgent recalibre
    # le profil effectif. Ex: beta_min=1.5 + profil="conservateur" → "agressif"
    # Lu par : MandateAgent uniquement (BLOC 2b réconciliation)

    beta_max_override: Optional[float]
    # Beta maximum explicitement saisi dans le formulaire (champ m-beta-max).
    # Utilisé pour définir le budget_risque.beta_max effectif dans le mandat.
    # Lu par : MandateAgent uniquement (BLOC 2b réconciliation)

    priorite_principale: Optional[str]
    # Priorité d'investissement déclarée par le client.
    # Valeurs : "preservation", "revenus", "croissance", "performance"
    # Lu par : MandateAgent

    # ┌─────────────────────────────────────────────────────────────────────────┐
    # │  SECTION 2 - OUTPUTS CUMULÉS PAR LES AGENTS                            │
    # │  Chaque clé est None jusqu'à ce que l'agent correspondant tourne.      │
    # │  L'agent écrit son output → le state est mergé dans workflow.py.       │
    # └─────────────────────────────────────────────────────────────────────────┘

    mandate: Optional[MandateOutput]
    # Écrit par : MandateAgent (étape 1)
    # Lu par    : EquityResearchAgent, PortfolioConstructionAgent,
    #             RiskManagementAgent, ExecutionAgent
    # Contient  : règles d'investissement, contraintes sectorielles, budget risque

    tickers: Optional[List[str]]
    # Tickers fournis par le PM via le formulaire ou l'API.
    # Lu par : EquityResearchAgent (fallback si non fourni → liste par défaut)

    research: Optional[List[ResearchOutput]]
    # Écrit par : EquityResearchAgent (étape 2)
    # Lu par    : PortfolioConstructionAgent (filtre les BUY)
    # Contient  : analyse détaillée + score conviction par titre (données réelles)

    portfolio: Optional[PortfolioOutput]
    # Écrit par : PortfolioConstructionAgent (étape 3, peut être réécrit plusieurs fois)
    # Lu par    : RiskManagementAgent, ExecutionAgent
    # Contient  : positions avec poids et valeurs USD, cash, répartition sectorielle

    portfolio_briefing: Optional[List[dict]]
    # Conversation PM ↔ agent AVANT la construction du portefeuille (niveau 3 d'interaction).
    # Format : [{"role": "user"|"assistant", "content": str}]
    # Écrit par : api.py (endpoint /api/portfolio/briefing) au fil des échanges
    # Lu par    : PortfolioConstructionAgent.run() (injecte les directives dans le prompt)
    # Vide ou None → l'agent construit avec son jugement standard (rétro-compat).

    research_brief: Optional[dict]
    # Brief structuré généré par le briefing conversationnel pré-Research.
    # Format : {"long_short": "long", "univers": "tech", "sous_secteur": "...",
    #           "style": "growth", "taille_capi": "large", "geo": "us",
    #           "nb_idees": 5, "contraintes": "...", "tickers_focus": [...]}
    # Écrit par : api.py (endpoint /api/research/briefing) à la fin du dialogue
    # Lu par    : EquityResearchAgent.run() pour cibler la recherche

    research_briefing_messages: Optional[List[dict]]
    # Historique de la conversation briefing Research (debug/audit).
    # Format : [{"role": "user"|"assistant", "content": str}]

    risk_report: Optional[RiskReport]
    # Écrit par : RiskManagementAgent (étape 4)
    # Lu par    : workflow.py (routing), PortfolioConstructionAgent (corrections boucle)
    # Contient  : statut PASS/AJUSTER/FAIL + violations + métriques calculées

    execution_output: Optional[ExecutionOutput]
    # Écrit par : ExecutionAgent (étape 5) - SEULEMENT si risk OK
    # Lu par    : runner.py (tableau des ordres)
    # Contient  : liste d'ordres BUY/SELL + coûts estimés + calendrier

    # ┌─────────────────────────────────────────────────────────────────────────┐
    # │  SECTION 3 - MÉTADONNÉES DU WORKFLOW                                   │
    # │  Variables techniques pour piloter la logique et l'affichage.          │
    # └─────────────────────────────────────────────────────────────────────────┘

    current_step: str
    # Trace l'étape courante. Ex: "mandate" → "research" → "portfolio"...
    # Chaque agent écrit la prochaine étape dans son retour.
    # Utilisé pour le routing (non encore exploité pour le routing - c'est
    # le statut du risk_report qui pilote la boucle dans workflow.py).

    portfolio_iteration: int
    # Numéro de l'itération courante dans la boucle Portfolio ↔ Risk.
    # Initialisé à 1 dans runner.py. Incrémenté par PortfolioConstructionAgent.
    # PortfolioConstructionAgent lit cette valeur pour savoir si c'est une correction.

    errors: List[str]
    # Erreurs non-fatales accumulées (un agent peut retourner {"errors": [...]}).
    # Le workflow continue malgré ces erreurs → pas de crash si un agent échoue partiellement.

    requires_human_review: bool
    # Mis à True pour déclencher la validation humaine avant export OMS.
    # Garantit que AUCUN ordre n'est transmis sans validation explicite du PM.

    human_approved: bool
    # Mis à True si l'utilisateur choisit "approuver" dans le prompt runner.py.
    # Pas encore utilisé pour bloquer le code - c'est une métadonnée d'audit.

    run_id: str
    # Identifiant unique du run. Ex: "57234B42" (8 caractères hex majuscules).
    # Généré dans runner.py via uuid.uuid4().hex[:8].upper().
    # Préfixe les fichiers d'export : "orders_57234B42.json", "run_57234B42.json"
