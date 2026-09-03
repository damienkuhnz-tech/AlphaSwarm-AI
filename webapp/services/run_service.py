"""
WEBAPP / SERVICES / RUN SERVICE - exécution du workflow en arrière-plan.

Contient la logique métier extraite d'api.py : sérialisation Pydantic,
validation numérique et le thread principal _run_workflow_thread qui pilote
les 5 agents et publie sa progression dans le run store partagé.
"""

import os
import sys
import json
import traceback
from datetime import datetime
from pathlib import Path

from orchestrator.workflow import build_workflow
from models.state import PortfolioState
from config.settings import settings

from webapp.run_store import _runs, _runs_lock

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  _serialize() - SÉRIALISATION RÉCURSIVE PYDANTIC → DICT JSON               │
# │  Convertit n'importe quel objet en quelque chose que json.dumps() accepte. │
# └─────────────────────────────────────────────────────────────────────────────┘

def _serialize(obj):
    """Sérialise récursivement les objets Pydantic en dict JSON-compatible."""
    if obj is None:
        return None
        # None reste None → JSON null → le frontend sait que cette étape n'a pas tourné

    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
        # model_dump(mode="json") : méthode Pydantic v2 → convertit récursivement en types JSON-safe
        # mode="json" garantit que les sous-modèles imbriqués sont aussi convertis en dict

    if isinstance(obj, list):
        return [_serialize(i) for i in obj]
        # Récursion : chaque élément de la liste est sérialisé individuellement
        # Ex: [ResearchOutput, ResearchOutput, ...] → [dict, dict, ...]

    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
        # Récursion sur les valeurs du dict
        # Ex: {"NVDA": ResearchOutput} → {"NVDA": dict}

    return obj
    # Scalaires (str, int, float, bool) : retournés tels quels - déjà JSON-compatibles


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║  THREAD WORKFLOW - EXÉCUTION EN ARRIÈRE-PLAN                               ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  _run_workflow_thread() - CŒUR DU RUN                                      │
# │  Lancé dans un thread séparé pour ne pas bloquer les requêtes Flask.       │
# │  Met à jour _runs[run_id] à chaque étape pour que le polling fonctionne.  │
# └─────────────────────────────────────────────────────────────────────────────┘

def _positive_float(value, default: float) -> float:
    """
    Convertit une saisie de formulaire en nombre strictement positif.
    Une valeur absente, vide, non numérique ou <= 0 retombe sur le défaut
    plutôt que de lever une ValueError au fond du thread (défaut C13).
    """
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return float(default)
    return parsed if parsed > 0 else float(default)


def _run_workflow_thread(run_id: str, params: dict):
    """
    Lance le workflow dans un thread séparé pour ne pas bloquer l'API.
    Met à jour _runs[run_id] à chaque étape.
    """
    try:
        # ── BLOC 1 : Construction du workflow ─────────────────────────────────
        # build_workflow() instancie les 5 agents + client Anthropic.
        # Fait ici (pas au démarrage) pour que chaque run ait ses propres agents.
        workflow = build_workflow()

        # ── BLOC 2 : Construction de l'état initial ───────────────────────────
        # L'état initial contient les paramètres saisis dans le formulaire HTML.
        # Les clés agents (mandate, research, ...) sont initialisées à None -
        # chaque agent les remplira au fur et à mesure du workflow.
        initial_state: PortfolioState = {
            "strategie":            params.get("strategie", "long-only equity global"),
            # Stratégie d'investissement : "long-only equity global", "long/short", etc.

            "capital":              _positive_float(params.get("capital"), 100_000_000),
            # Capital en USD. _positive_float : rejette proprement une saisie non
            # numérique ou négative au lieu de lever dans le thread (défaut C13).

            "benchmark":            params.get("benchmark", "MSCI World"),
            # Indice de référence pour mesurer la performance relative.

            "horizon":              params.get("horizon", "3-5 ans"),
            # Horizon d'investissement : influence le niveau de risque acceptable.

            "profil_risque":        params.get("profil_risque", "equilibre"),
            # Profil : "conservateur", "equilibre", "croissance", "agressif"
            # Détermine les contraintes beta et sectorielles dans MandateAgent.

            "perte_max_toleree":    params.get("perte_max_toleree"),
            # Drawdown max accepté (ex: 15.0 = 15%). None si non renseigné.

            "priorite_principale":  params.get("priorite_principale", "croissance"),
            # Objectif principal : "croissance", "revenu", "preservation_capital"

            # ── Contraintes beta override depuis le formulaire ─────────────────
            # Permettent au MandateAgent de réconcilier le profil_risque si le
            # PM a entré des betas explicitement incompatibles avec le dropdown.
            "beta_min_override":    params.get("beta_min_override"),
            "beta_max_override":    params.get("beta_max_override"),

            # ── Nombre de positions cible (saisi par le gérant) ────────────────
            # Lu par MandateAgent → fixe mandate.nombre_positions_cible.
            # None si non renseigné → l'agent garde son défaut.
            "nombre_positions_cible": params.get("nombre_positions_cible"),

            # ── Sorties des agents (remplies au fil du workflow) ───────────────
            "mandate":         None,  # MandateAgent → MandateOutput
            "research":        None,  # EquityResearchAgent → List[ResearchOutput]
            "portfolio":       None,  # PortfolioConstructionAgent → PortfolioOutput
            "risk_report":     None,  # RiskManagementAgent → RiskReport
            "execution_output": None, # ExecutionAgent → ExecutionOutput

            # ── Briefing PM (niveau 3 - conversation avant construction) ───────
            # Liste de messages [{"role": "user"|"assistant", "content": str}].
            # Alimentée par /api/portfolio/briefing avant que le PM clique "Construire".
            # Lue par PortfolioConstructionAgent pour respecter les directives.
            "portfolio_briefing": params.get("portfolio_briefing") or [],

            # ── Brief Research (briefing conversationnel pré-recherche) ────────
            # Objet structuré généré par le dialogue PM ↔ agent dans /api/research/briefing.
            # Lu par EquityResearchAgent.run() pour cibler la recherche.
            "research_brief":              params.get("research_brief")              or None,
            "research_briefing_messages":  params.get("research_briefing_messages")  or [],

            # ── Métadonnées du run ─────────────────────────────────────────────
            "current_step":         "mandate",  # Étape courante (mise à jour par workflow)
            "portfolio_iteration":  1,           # Numéro d'itération boucle Risk↔Portfolio
            "errors":               [],          # Erreurs non fatales accumulées
            "requires_human_review": False,      # Passe à True si validation humaine requise
            "human_approved":       False,       # Passe à True après /approve
            "run_id":               run_id,      # ID du run (tracé dans tout le workflow)
        }

        # ── BLOC 2b : REPRISE D'UN RUN PRÉCÉDENT (défaut A2) ──────────────────
        # Sans ceci, relancer un seul agent repartait d'un état vide : le moteur
        # reconstruisait mandat, recherche et portefeuille depuis zéro, puis
        # jugeait CE nouveau portefeuille - pas celui affiché à l'écran.
        # On réutilise donc les objets Pydantic du run précédent tels quels
        # (jamais leur version sérialisée, qui ne se reconstruit pas fidèlement).
        from_run_id = params.get("from_run_id")
        if from_run_id:
            with _runs_lock:
                prev = _runs.get(from_run_id)
                prev_state = dict(prev.get("_state_obj") or {}) if prev else {}
            reprises = []
            for key in ("mandate", "research", "research_reports",
                        "portfolio", "risk_report", "execution_output",
                        "portfolio_iteration"):
                value = prev_state.get(key)
                if value:
                    initial_state[key] = value
                    reprises.append(key)
            if reprises:
                print(f"[run {run_id}] reprise depuis {from_run_id} : "
                      f"{', '.join(reprises)}", flush=True)
            else:
                print(f"[run {run_id}] from_run_id={from_run_id} sans état "
                      f"réutilisable - reconstruction complète.", flush=True)

        # ── BLOC 3 : Hook de progression pour la recherche ────────────────────
        # EquityResearchAgent appelle ce hook après chaque ticker analysé.
        # Permet à l'interface d'afficher "3/10 tickers analysés" en temps réel
        # pendant que l'agent tourne (sans attendre la fin de toute la recherche).
        def _research_progress_hook(partial_research, done_count, total_count):
            with _runs_lock:
                if run_id in _runs:
                    # Écrase le snapshot partiel de research avec les résultats partiels
                    _runs[run_id]["partial_state"]["research"] = _serialize(partial_research)
                    # Met à jour le compteur de progression (ex: {"done": 3, "total": 10})
                    _runs[run_id]["research_progress"] = {
                        "done": done_count,
                        "total": total_count
                    }

        initial_state["_research_progress_hook"] = _research_progress_hook
        # Le hook est injecté dans le state pour que EquityResearchAgent puisse l'appeler.
        # Clé "_research_progress_hook" : préfixe "_" = clé privée, pas exposée au LLM.

        # ── BLOC 4 : Labels des étapes (pour l'interface) ─────────────────────
        # Mappe le nom interne de chaque étape (ex: "mandate") vers son label
        # lisible pour l'affichage dans l'interface (ex: "1/8 - Mandate Agent").
        step_labels = {
            "mandate":   "1/5 - Mandate Agent",
            "research":  "2/5 - Equity Research Agent",
            "portfolio": "3/5 - Portfolio Construction Agent",
            "risk":      "4/5 - Risk Management Agent",
            "execution": "5/5 - Execution Agent",
        }

        # ── BLOC 5 : Callback appelé après chaque étape du workflow ───────────
        # WorkflowEngine appelle on_step_done(node, state) après chaque agent.
        # Ce callback met à jour _runs[run_id] pour que le polling GET /api/run/<id>
        # retourne toujours l'état le plus récent.
        def on_step_done(node: str, state: PortfolioState):
            label = step_labels.get(node, node)
            with _runs_lock:
                # Ajoute une entrée dans le journal des étapes terminées
                _runs[run_id]["log"].append({
                    "step":      node,               # Nom interne (ex: "mandate")
                    "label":     label,              # Nom lisible (ex: "1/8 - Mandate Agent")
                    "timestamp": datetime.utcnow().isoformat() + "Z",  # Heure UTC ISO 8601
                })
                _runs[run_id]["current_step"] = node
                # Snapshot partiel : les 4 premières étapes sont affichées pendant le run
                # pour que l'interface puisse montrer du contenu progressivement.
                # FUSION et non écrasement : une réécriture complète effaçait ce
                # que _research_progress_hook venait de publier (défaut C3).
                snapshot = _runs[run_id].get("partial_state") or {}
                snapshot.update({
                    "mandate":   _serialize(state.get("mandate")),
                    "research":  _serialize(state.get("research", [])),
                    "portfolio": _serialize(state.get("portfolio")),
                })
                _runs[run_id]["partial_state"] = snapshot

        # ── BLOC 6 : Lancement du workflow ────────────────────────────────────
        # Si target_step est fourni dans params → mode agent individuel.
        # Sinon → workflow complet (5 agents).
        target_step = params.get("target_step")
        final_state = workflow.run(
            initial_state,
            on_step_done=on_step_done,
            target_step=target_step,
        )

        # ── BLOC 7 : Export automatique du run complet ────────────────────────
        # Sauvegarde l'état final dans outputs/run_{run_id}.json.
        # Utile pour : debug, audit, replay, export manuel.
        Path(settings.OUTPUTS_DIR).mkdir(parents=True, exist_ok=True)
        run_path = os.path.join(settings.OUTPUTS_DIR, f"run_{run_id}.json")

        # _serialize (définie ligne 48) gère : None, Pydantic, list, dict récursifs.
        # On ne redéfinit pas _serial ici - utiliser _serialize partout.
        run_payload = {
            "run_id":    run_id,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "mandate":   _serialize(final_state.get("mandate")),
            "research":  _serialize(final_state.get("research", [])),
            "portfolio": _serialize(final_state.get("portfolio")),
            "risk":      _serialize(final_state.get("risk_report")),
            "execution": _serialize(final_state.get("execution_output")),
            # Erreurs non fatales accumulées par les agents (un agent qui échoue
            # n'effondre plus le run : il est marqué ici et le run se termine en
            # "done" avec résultats partiels au lieu de basculer en "error").
            "errors":    _serialize(final_state.get("errors", [])),
        }
        with open(run_path, "w", encoding="utf-8") as f:
            json.dump(run_payload, f, ensure_ascii=False, indent=2)
            # ensure_ascii=False : garde les caractères UTF-8 (accents, symboles)
            # indent=2 : indentation pour lisibilité humaine

        # ── BLOC 8 : Mise à jour du statut "done" ─────────────────────────────
        # Passe le run de "running" à "done" → le polling GET /api/run/<id>
        # retournera status="done" et l'interface affichera les résultats.
        with _runs_lock:
            _runs[run_id]["status"]      = "done"
            _runs[run_id]["final_state"] = run_payload   # Résultats sérialisés
            _runs[run_id]["run_path"]    = run_path      # Chemin du fichier JSON
            # Objets Pydantic conservés en mémoire pour permettre à un run ciblé
            # de repartir de cet état (from_run_id). Jamais renvoyés au client :
            # get_run_status ne sérialise qu'une liste blanche de champs.
            _runs[run_id]["_state_obj"]  = final_state

    except Exception as e:
        # ── BLOC 9 : Gestion d'erreur fatale ─────────────────────────────────
        # Si n'importe quel agent crashe et lève une exception non rattrapée,
        # on passe le run en statut "error" avec le message d'erreur.
        # L'interface affichera un message d'erreur au lieu de rester bloquée.
        #
        # On imprime la stack COMPLÈTE sur stderr (visible dans la console serveur)
        # et on la persiste dans le run - sans ça, str(e) seul masque la cause
        # racine (ex: une ValidationError Pydantic dont le détail est dans la trace).
        tb = traceback.format_exc()
        print(
            f"[run {run_id}] AGENT CRASH ({type(e).__name__}): {e}\n{tb}",
            file=sys.stderr, flush=True,
        )
        with _runs_lock:
            _runs[run_id]["status"]    = "error"
            _runs[run_id]["error"]     = f"{type(e).__name__}: {e}"
            _runs[run_id]["traceback"] = tb

