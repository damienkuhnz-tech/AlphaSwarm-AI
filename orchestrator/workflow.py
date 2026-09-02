"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  ORCHESTRATOR / WORKFLOW — MOTEUR DE SÉQUENCEMENT DES AGENTS                ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Rôle : instancier les 5 agents et définir leur ordre d'exécution.         ║
║  Ce fichier est le "chef d'orchestre" — il ne contient aucune logique LLM. ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Ordre d'exécution :                                                        ║
║    1. MandateAgent               → formalise les règles d'investissement    ║
║    2. EquityResearchAgent         → analyse les tickers (yfinance + Claude)  ║
║    3. PortfolioConstructionAgent  → construit l'allocation optimale          ║
║    4. RiskManagementAgent         → vérifie le budget de risque              ║
║       ↕ Boucle si statut = AJUSTER (max MAX_PORTFOLIO_ITERATIONS fois)      ║
║    5. ExecutionAgent              → prépare les ordres OMS (si risk OK)      ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  IMPORTS                                                                    │
# └─────────────────────────────────────────────────────────────────────────────┘

from __future__ import annotations
# Permet d'utiliser des annotations de type avec des strings forward references
# (ex: Callable | None) même sur Python 3.9 qui ne supporte pas le | natif.

from typing import Callable
# Callable : type pour les fonctions passées en paramètre (on_step_done, agent_fn)

from rich.console import Console
# Console Rich : utilisé pour afficher le message d'alerte de blocage.

from llm.client import get_client
# Factory provider-agnostique : crée un client Anthropic OU Groq selon
# LLM_PROVIDER dans .env. L'objet expose la même API que anthropic.Anthropic.

from models.state import PortfolioState
# Type du dict central partagé entre tous les agents.

from config.settings import settings
# settings.MAX_PORTFOLIO_ITERATIONS : limite de la boucle Risk↔Portfolio

# ── Import des 5 agents au niveau MODULE ──────────────────────────────────────
from agents import (
    MandateAgent,
    EquityResearchAgent,
    PortfolioConstructionAgent,
    RiskManagementAgent,
    ExecutionAgent,
)

# Console avec force_terminal=True pour que les couleurs ANSI s'affichent
# même si stdout est redirigé (ex: python main.py > log.txt).
# legacy_windows=False : utilise le mode ANSI moderne (pas l'ancien cmd.exe).
console = Console(force_terminal=True, legacy_windows=False)


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║  CLASSE WORKFLOWENGINE                                                      ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

class WorkflowEngine:
    """
    Moteur de workflow simple :
    - Exécute les agents en séquence
    - Gère la boucle Risk → Portfolio (max MAX_PORTFOLIO_ITERATIONS)
    - Gère le routing conditionnel : Execution seulement si risk OK
    """

    # ┌─────────────────────────────────────────────────────────────────────────┐
    # │  __init__ — INSTANCIATION DES 5 AGENTS                                 │
    # └─────────────────────────────────────────────────────────────────────────┘

    def __init__(self) -> None:

        # ── Client LLM partagé ────────────────────────────────────────────────
        # On crée UN SEUL client (Anthropic OU Groq selon LLM_PROVIDER) pour tous
        # les agents. Avantage : une seule connexion HTTP persistante.
        shared_client = get_client()

        # ── Instanciation des 5 agents ────────────────────────────────────────
        # Tous héritent de BaseAgent et reçoivent le même client.
        # À ce stade, aucun LLM n'est appelé — on prépare juste les instances.
        self.mandate_agent   = MandateAgent(client=shared_client)
        self.research_agent  = EquityResearchAgent(client=shared_client)
        self.portfolio_agent = PortfolioConstructionAgent(client=shared_client)
        self.risk_agent      = RiskManagementAgent(client=shared_client)
        self.execution_agent = ExecutionAgent(client=shared_client)

    # ┌─────────────────────────────────────────────────────────────────────────┐
    # │  GRAPHE DE DÉPENDANCES DÉCLARÉ                                         │
    # │  Une seule source de vérité pour l'ordre des étapes. Le mode ciblé      │
    # │  s'en sert pour remonter les prérequis manquants ; ajouter un agent     │
    # │  ne demande plus de toucher quatre branches de if/elif (E5).            │
    # └─────────────────────────────────────────────────────────────────────────┘

    _DEPS = {
        "mandate":   [],
        "research":  ["mandate"],
        "portfolio": ["mandate", "research"],
        "risk":      ["mandate", "research", "portfolio"],
        "execution": ["mandate", "research", "portfolio", "risk"],
    }

    # Clé du state qui prouve qu'une étape a déjà produit son résultat.
    _STATE_KEY = {
        "mandate":   "mandate",
        "research":  "research",
        "portfolio": "portfolio",
        "risk":      "risk_report",
        "execution": "execution_output",
    }

    # ┌─────────────────────────────────────────────────────────────────────────┐
    # │  _execution_blocked() — GARDE-FOU UNIQUE AVANT PRÉPARATION D'ORDRES     │
    # │  Appliqué À L'IDENTIQUE au mode complet et au mode ciblé.               │
    # │  AVANT : la branche target_step == "execution" n'exécutait jamais       │
    # │  l'agent de risque et ne consultait jamais risk_report.statut — la      │
    # │  seule contrainte dure du workflow était contournable (défaut A1).      │
    # └─────────────────────────────────────────────────────────────────────────┘

    def _execution_blocked(self, state: PortfolioState) -> bool:
        """True si aucun ordre ne doit être préparé. Trace la raison dans errors."""
        risk = state.get("risk_report")

        if risk is None:
            msg = ("execution bloquée — aucun rapport de risque disponible : "
                   "aucun ordre ne peut être préparé sans verdict de risque.")
        elif risk.statut == "FAIL":
            msg = (f"execution bloquée — verdict de risque FAIL "
                   f"({len(risk.violations)} violation(s) relevée(s)).")
        else:
            return False

        console.print(f"  [red]⚠[/red]  {msg}")
        state["errors"] = (state.get("errors") or []) + [msg]
        return True

    # ┌─────────────────────────────────────────────────────────────────────────┐
    # │  _run_step() — EXÉCUTION D'UNE ÉTAPE + MERGE DU STATE                  │
    # └─────────────────────────────────────────────────────────────────────────┘

    def _run_step(
        self,
        label:    str,                # Nom de l'étape (ex: "mandate", "risk")
        agent_fn: Callable,           # Méthode run() de l'agent à exécuter
        state:    PortfolioState,     # État courant du workflow
        on_done:  Callable | None = None,  # Callback d'affichage (runner.py)
    ) -> PortfolioState:
        """Exécute un agent, merge les updates dans le state, notifie le callback."""

        # ── Exécution de l'agent (filet anti-crash) ───────────────────────────
        # Un agent peut lever : ValueError (JSON LLM vide/invalide via _parse_json),
        # ValidationError Pydantic (champ manquant), ou une erreur réseau épuisée.
        # AVANT, ces exceptions remontaient et faisaient passer TOUT le run en
        # "error" (api.py) — un seul agent en échec effondrait le workflow entier.
        # Désormais on les capture, on les transforme en erreur accumulée et on
        # laisse le workflow continuer (les agents suivants ont leurs propres
        # gardes de préconditions et le routing gère les outputs manquants).
        try:
            updates = agent_fn(state)
        except Exception as agent_err:
            msg = f"{label}: {type(agent_err).__name__}: {agent_err}"
            console.print(f"  [red]✗[/red]  Agent '{label}' a échoué — {msg}")
            updates = {"errors": [msg]}

        # ── Guard : l'agent doit retourner un dict ────────────────────────────
        if not isinstance(updates, dict):
            updates = {
                "errors": [
                    f"{label}: a retourné {type(updates).__name__!r} au lieu d'un dict "
                    f"— vérifier la méthode run() de l'agent."
                ]
            }

        # ── Merge dans le state (errors ACCUMULÉS, pas écrasés) ────────────────
        # {**state, **updates} écraserait state["errors"] par updates["errors"].
        # On extrait donc errors et on l'étend pour conserver l'historique complet.
        new_errors = updates.get("errors")
        merged = {**state, **updates}
        if new_errors:
            merged["errors"] = (state.get("errors") or []) + list(new_errors)
        state = merged

        # ── Callback d'affichage ──────────────────────────────────────────────
        if on_done:
            try:
                on_done(label, state)
            except Exception as cb_err:
                print(
                    f"[workflow] Callback on_done pour '{label}' a echoue "
                    f"({type(cb_err).__name__}: {cb_err}) — workflow continue.",
                    flush=True,
                )

        return state

    # ┌─────────────────────────────────────────────────────────────────────────┐
    # │  run() — POINT D'ENTRÉE PRINCIPAL DU WORKFLOW                           │
    # │  Exécute les 5 agents dans l'ordre avec routing conditionnel.           │
    # └─────────────────────────────────────────────────────────────────────────┘

    def run(
        self,
        state:         PortfolioState,       # État initial fourni par runner.py
        on_step_done:  Callable | None = None, # Callback appelé après chaque agent
        target_step:   str | None = None,    # Si fourni : exécuter uniquement cet agent
    ) -> PortfolioState:                     # Retourne l'état final complet
        """
        Exécute le workflow.
        - Si target_step est None : exécute le workflow complet (5 agents).
        - Si target_step ∈ {"mandate","research","portfolio","risk","execution"} :
          exécute uniquement cet agent (nécessite que les prérequis soient dans state).
        Callback on_step_done(label, state) → appelé après chaque agent.
        """

        # ── Helper local : évite de répéter "state = self._run_step(...)" ─────
        def step(label: str, fn: Callable) -> None:
            nonlocal state
            state = self._run_step(label, fn, state, on_step_done)

        # ┌─────────────────────────────────────────────────────────────────────┐
        # │  MODE INDIVIDUEL — un seul agent                                    │
        # └─────────────────────────────────────────────────────────────────────┘
        if target_step:
            agents = {
                "mandate":   self.mandate_agent.run,
                "research":  self.research_agent.run,
                "portfolio": self.portfolio_agent.run,
                "risk":      self.risk_agent.run,
                "execution": self.execution_agent.run,
            }
            if target_step not in agents:
                state["errors"] = (state.get("errors") or []) + [
                    f"target_step inconnu : {target_step!r}"
                ]
                return state

            # ── Remontée récursive des prérequis ──────────────────────────────
            # Une étape n'est rejouée QUE si son résultat est absent du state.
            # Quand l'API repart d'un run précédent (from_run_id), les prérequis
            # sont déjà là : on ne reconstruit rien et l'agent ciblé travaille
            # bien sur le portefeuille que le gérant a sous les yeux (défaut A2).
            def ensure(name: str) -> None:
                nonlocal state
                if state.get(self._STATE_KEY[name]):
                    return
                for dep in self._DEPS[name]:
                    ensure(dep)
                if name == "portfolio":
                    state["portfolio_iteration"] = state.get("portfolio_iteration", 1)
                state = self._run_step(name, agents[name], state, on_step_done)

            for dep in self._DEPS[target_step]:
                ensure(dep)

            # ── Garde-fou identique au mode complet ───────────────────────────
            if target_step == "execution" and self._execution_blocked(state):
                return state

            if target_step == "portfolio":
                state["portfolio_iteration"] = state.get("portfolio_iteration", 1)

            step(target_step, agents[target_step])
            return state

        # ┌─────────────────────────────────────────────────────────────────────┐
        # │  BLOC 1 — ÉTAPES 1-2 : MANDATE → RESEARCH                         │
        # └─────────────────────────────────────────────────────────────────────┘

        step("mandate",  self.mandate_agent.run)
        # → LIT  : strategie, capital, benchmark, horizon (depuis state initial)
        # → ÉCRIT: state["mandate"] = MandateOutput (règles, contraintes, ESG)

        # ── Short-circuit : sans mandat, tous les agents suivants échoueraient ──
        # (research/portfolio/risk/execution dépendent tous du mandat). Plutôt que
        # d'empiler une cascade d'erreurs, on s'arrête net avec l'erreur du mandat
        # déjà accumulée dans state["errors"] par _run_step.
        if state.get("mandate") is None:
            console.print(
                "  [red]⚠[/red]  Mandat non généré — workflow interrompu "
                "(étapes suivantes ignorées)."
            )
            return state

        step("research", self.research_agent.run)
        # → LIT  : state["tickers"] ou liste par défaut, state["mandate"]
        # → ÉCRIT: state["research"] = List[ResearchOutput] (analyses détaillées)
        #          state["research_reports"] = dict des chemins vers les HTML

        # ┌─────────────────────────────────────────────────────────────────────┐
        # │  BLOC 2 — ÉTAPES 3-4 : BOUCLE PORTFOLIO ↔ RISK                    │
        # └─────────────────────────────────────────────────────────────────────┘

        for iteration in range(1, settings.MAX_PORTFOLIO_ITERATIONS + 1):

            state["portfolio_iteration"] = iteration

            step("portfolio", self.portfolio_agent.run)
            # → LIT  : state["research"], state["mandate"], state["risk_report"] (si iter > 1)
            # → ÉCRIT: state["portfolio"] = PortfolioOutput

            step("risk",      self.risk_agent.run)
            # → LIT  : state["portfolio"], state["mandate"]
            # → ÉCRIT: state["risk_report"] = RiskReport (statut + violations + métriques)

            risk = state.get("risk_report")

            # ── PASS : portefeuille conforme → on sort de la boucle ───────────
            if risk is None or risk.statut == "PASS":
                break

            # ── FAIL : violation critique → on sort SANS reboucler ────────────
            if risk.statut == "FAIL":
                break

            # ── AJUSTER : violations non critiques → on reboucle si possible ──
            if iteration == settings.MAX_PORTFOLIO_ITERATIONS:
                break
            # Sinon : la boucle for continue à l'itération suivante

        # ┌─────────────────────────────────────────────────────────────────────┐
        # │  BLOC 3 — ROUTING CONDITIONNEL : EXECUTION ou BLOCAGE              │
        # │  On n'exécute les ordres QUE si le risk est OK.                    │
        # └─────────────────────────────────────────────────────────────────────┘

        # Un seul et même garde-fou pour les deux modes (cf. _execution_blocked).
        # Note : un risk_report absent bloque désormais AUSSI la préparation
        # d'ordres. Avant, un agent de risque en échec laissait passer les ordres.
        if not self._execution_blocked(state):
            # ── CAS NORMAL : on prépare les ordres ───────────────────────────
            step("execution", self.execution_agent.run)
            # → LIT  : state["portfolio"], state["mandate"]
            # → ÉCRIT: state["execution_output"] = ExecutionOutput (liste d'ordres)

        return state  # Retourne l'état complet


# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  FACTORY build_workflow()                                                   │
# └─────────────────────────────────────────────────────────────────────────────┘

def build_workflow() -> WorkflowEngine:
    """Factory — retourne un WorkflowEngine prêt à l'emploi."""
    return WorkflowEngine()
