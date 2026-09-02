"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  ALPHASWARM API — PONT ENTRE L'INTERFACE HTML ET LES AGENTS PYTHON            ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Rôle : serveur Flask qui expose les agents Python via une API REST.        ║
║  L'interface HTML soumet le formulaire mandat → l'API lance le workflow.   ║
║                                                                              ║
║  Lancement : python api.py                                                  ║
║  Port      : 5001 (pour ne pas conflicter avec le serveur HTML 7432)        ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  IMPORTS STANDARDS                                                          │
# └─────────────────────────────────────────────────────────────────────────────┘

import sys       # sys.platform : détecte Windows pour le fix UTF-8
import io        # io.TextIOWrapper : re-wrapping stdout/stderr en UTF-8
import os        # os.path.join : construction de chemins de fichiers
import json      # json.dump : export du run complet en JSON
import uuid      # uuid.uuid4 : génère un identifiant unique par run
import logging   # logging.getLogger : supprime les logs werkzeug (spam terminal)
import threading # threading.Thread : lance le workflow sans bloquer l'API
import traceback # traceback.format_exc : capture la stack complète d'un agent qui crashe
from datetime import datetime  # datetime.utcnow : horodatage des runs
from pathlib import Path       # Path.mkdir : crée les dossiers outputs/exports
import copy                      # deepcopy : snapshot cohérent de l'état d'un run
import html as _html             # escape : neutralise le HTML dans les pages d'erreur

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  FIX UTF-8 WINDOWS                                                          │
# │  Sur Windows, stdout/stderr utilisent cp1252 par défaut → accents cassés.  │
# │  On force UTF-8 avant tout import Flask pour que les logs s'affichent bien.│
# └─────────────────────────────────────────────────────────────────────────────┘

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    # errors="replace" : si un caractère UTF-8 ne peut pas s'afficher → "?" au lieu de crash

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  IMPORTS FLASK ET MODULES INTERNES                                          │
# └─────────────────────────────────────────────────────────────────────────────┘

from flask import Flask, request, jsonify, send_from_directory
# Flask          : micro-framework web — gère les routes HTTP
# request        : accède au body JSON des requêtes POST
# jsonify        : convertit un dict Python en réponse JSON avec Content-Type correct
# send_from_directory : sert des fichiers statiques (rapports HTML, interface)

from flask_cors import CORS
# CORS : autorise les requêtes depuis un domaine différent (ex: fichier HTML ouvert localement)
# Sans CORS, le navigateur bloquerait les appels fetch() vers localhost:5001

from orchestrator.workflow import build_workflow
# build_workflow() : factory qui instancie les 5 agents + le client Anthropic partagé

from models.state import PortfolioState
# Type du dict central partagé entre les agents — utilisé pour l'annotation de type

from config.settings import settings
# settings.OUTPUTS_DIR, settings.EXPORTS_DIR : chemins des dossiers de sortie

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  CRÉATION DE L'APPLICATION FLASK                                            │
# └─────────────────────────────────────────────────────────────────────────────┘

app = Flask(__name__, static_folder=".")
# __name__     : nom du module courant (api) → Flask utilise ce répertoire comme base
# static_folder="." : sert les fichiers statiques depuis la racine du projet
#                     → permet de servir finagent_full_interface.html directement

CORS(app, origins=["http://localhost:5001", "http://127.0.0.1:5001"])
# Autorise les requêtes cross-origin uniquement depuis le serveur local
# Restreint aux origines connues pour éviter les requêtes cross-origin malveillantes

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  SILENCE DES LOGS WERKZEUG                                                  │
# │  Sans ça : chaque poll de l'interface (toutes les 2s) génère une ligne     │
# │  "\r" dans le terminal → prompt PowerShell qui "boucle" visuellement.      │
# └─────────────────────────────────────────────────────────────────────────────┘

logging.getLogger("werkzeug").setLevel(logging.ERROR)
# logging.ERROR : n'affiche que les erreurs réelles (500, etc.), pas les accès normaux
# Les GET /api/run/xxx répétés toutes les 2s ne s'affichent plus dans le terminal

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  STORE EN MÉMOIRE DES RUNS                                                  │
# │  Clé = run_id (ex: "A3F7B2C1"), valeur = dict complet du run.              │
# │  Tout est en RAM — pas de base de données.                                  │
# └─────────────────────────────────────────────────────────────────────────────┘

_runs: dict = {}
# Dict global : survit entre les requêtes Flask (scope module).
# Contient tous les runs en cours et terminés depuis le démarrage de l'API.
# Ex: {"A3F7B2C1": {"status": "running", "log": [...], ...}}
_MAX_RUNS = 20  # Limite mémoire : on garde les N derniers runs pour éviter une fuite

_runs_lock = threading.Lock()
# Verrou pour accès thread-safe à _runs.
# Nécessaire car : le thread workflow (background) et les requêtes Flask (autre thread)
# lisent/écrivent _runs en même temps. Sans lock → race condition → crash ou données corrompues.


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║  HELPERS                                                                    ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  _serialize() — SÉRIALISATION RÉCURSIVE PYDANTIC → DICT JSON               │
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
    # Scalaires (str, int, float, bool) : retournés tels quels — déjà JSON-compatibles


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║  THREAD WORKFLOW — EXÉCUTION EN ARRIÈRE-PLAN                               ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  _run_workflow_thread() — CŒUR DU RUN                                      │
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
        # Les clés agents (mandate, research, ...) sont initialisées à None —
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

            # ── Briefing PM (niveau 3 — conversation avant construction) ───────
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
        # jugeait CE nouveau portefeuille — pas celui affiché à l'écran.
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
                      f"réutilisable — reconstruction complète.", flush=True)

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
        # lisible pour l'affichage dans l'interface (ex: "1/8 — Mandate Agent").
        step_labels = {
            "mandate":   "1/5 — Mandate Agent",
            "research":  "2/5 — Equity Research Agent",
            "portfolio": "3/5 — Portfolio Construction Agent",
            "risk":      "4/5 — Risk Management Agent",
            "execution": "5/5 — Execution Agent",
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
                    "label":     label,              # Nom lisible (ex: "1/8 — Mandate Agent")
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
        # On ne redéfinit pas _serial ici — utiliser _serialize partout.
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
        # et on la persiste dans le run — sans ça, str(e) seul masque la cause
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


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║  ROUTES API                                                                 ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  POST /api/run — DÉMARRAGE D'UN NOUVEAU RUN                                │
# │  Reçoit les paramètres du formulaire HTML → lance le workflow en thread.  │
# └─────────────────────────────────────────────────────────────────────────────┘

@app.route("/api/run", methods=["POST"])
def start_run():
    """
    Démarre un workflow agent en arrière-plan.
    Body JSON : {strategie, capital, benchmark, horizon,
                 profil_risque, perte_max_toleree, priorite_principale, ...}
    Returns   : {run_id, status: "started"}
    """
    # ── Lecture des paramètres du body JSON ───────────────────────────────────
    params = request.get_json(force=True) or {}
    # force=True : parse le JSON même si Content-Type n'est pas application/json
    # or {}      : si body vide → dict vide (pas d'erreur)

    # ── Génération d'un identifiant unique ────────────────────────────────────
    run_id = uuid.uuid4().hex[:8].upper()
    # uuid4() : UUID aléatoire (ex: "a3f7b2c1-...")
    # .hex[:8].upper() : garde les 8 premiers caractères hexadécimaux en majuscules
    # Ex résultat : "A3F7B2C1"

    # ── Initialisation de l'entrée dans le store ──────────────────────────────
    with _runs_lock:
        # Purge des runs les plus anciens si la limite est atteinte
        if len(_runs) >= _MAX_RUNS:
            # Trie par date de démarrage, supprime les plus anciens
            sorted_ids = sorted(_runs, key=lambda k: _runs[k].get("started_at", ""))
            for old_id in sorted_ids[:len(_runs) - _MAX_RUNS + 1]:
                del _runs[old_id]
        _runs[run_id] = {
            "status":        "running",   # État initial : en cours
            "run_id":        run_id,
            "params":        params,      # Sauvegarde des paramètres d'entrée
            "log":           [],          # Journal des étapes (rempli par on_step_done)
            "current_step":  "mandate",   # Première étape attendue
            "partial_state": {},          # Snapshot partiel (mis à jour pendant le run)
            "final_state":   None,        # Résultat final (rempli quand status="done")
            "error":         None,        # Message d'erreur (rempli si status="error")
            "started_at":    datetime.utcnow().isoformat() + "Z",
        }

    # ── Lancement du thread workflow ──────────────────────────────────────────
    t = threading.Thread(
        target=_run_workflow_thread,
        args=(run_id, params),
        daemon=True,
        # daemon=True : le thread s'arrête automatiquement si le processus principal s'arrête
        # Sans daemon=True : fermer l'API attendrait la fin du workflow (plusieurs minutes)
    )
    t.start()

    return jsonify({"run_id": run_id, "status": "started"})
    # L'interface reçoit immédiatement le run_id → commence le polling GET /api/run/<id>


# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  GET /api/run/<run_id> — POLLING DU STATUT                                 │
# │  Appelé toutes les 2s par l'interface pour mettre à jour l'affichage.     │
# └─────────────────────────────────────────────────────────────────────────────┘

@app.route("/api/run/<run_id>", methods=["GET"])
def get_run_status(run_id: str):
    """
    Retourne le statut d'un run en cours ou terminé.
    Polling : l'interface appelle toutes les 2s pour mettre à jour l'affichage.
    Returns : {run_id, status, current_step, log, partial_state, final_state}
    """
    # Snapshot COMPLET pris SOUS verrou (défaut C2) : auparavant seule la
    # référence était copiée, et jsonify() itérait le dict hors verrou pendant
    # que le thread worker le mutait — snapshot incohérent, voire RuntimeError.
    with _runs_lock:
        run = _runs.get(run_id)
        snapshot = copy.deepcopy({
            # Liste blanche : ni traceback, ni params, ni _state_obj ne sortent
            # du serveur (défaut A7). Le détail de l'erreur reste dans la console.
            "run_id":            run.get("run_id"),
            "status":            run.get("status"),
            "current_step":      run.get("current_step"),
            "log":               run.get("log"),
            "partial_state":     run.get("partial_state"),
            "research_progress": run.get("research_progress"),
            "final_state":       run.get("final_state"),
            "error":             run.get("error"),
            "started_at":        run.get("started_at"),
        }) if run else None

    if not snapshot:
        return jsonify({"error": f"Run {run_id} introuvable"}), 404
        # 404 : run_id invalide ou API redémarrée (les runs ne persistent pas au redémarrage)

    return jsonify(snapshot)


# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  POST /api/run/<run_id>/approve — VALIDATION HUMAINE + EXPORT OMS          │
# │  Déclenché quand le PM clique "Approuver" dans l'interface.               │
# └─────────────────────────────────────────────────────────────────────────────┘

@app.route("/api/run/<run_id>/approve", methods=["POST"])
def approve_run(run_id: str):
    """
    Approuve le run (export des ordres OMS).
    Returns : {status: "approved", orders_path}
    """
    with _runs_lock:
        run = _runs.get(run_id)

    # ── Vérification que le run est terminé ───────────────────────────────────
    if not run or run["status"] != "done":
        return jsonify({"error": "Run non terminé ou introuvable"}), 400
        # 400 : on ne peut pas approuver un run en cours ou en erreur

    # ── Vérification qu'il y a des ordres à exporter ─────────────────────────
    final = run.get("final_state", {})
    execution = final.get("execution")
    if not execution:
        return jsonify({"error": "Pas d'ordres à exporter"}), 400
        # Cas : risk FAIL → ExecutionAgent sauté → pas d'ordres

    # ── Export du fichier OMS ─────────────────────────────────────────────────
    Path(settings.EXPORTS_DIR).mkdir(parents=True, exist_ok=True)
    filepath = os.path.join(settings.EXPORTS_DIR, f"orders_{run_id}.json")
    # Ex: exports/orders_A3F7B2C1.json

    payload = {
        "run_id":    run_id,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "statut":    "APPROUVE_POUR_OMS",
        "ordres":    execution.get("ordres", []),
        # Liste des ordres : [{"ticker": "NVDA", "action": "BUY", "quantite": 1250, ...}]
        "couts":     execution.get("couts_transaction", {}),
        # Estimation des coûts de transaction totaux
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    return jsonify({"status": "approved", "orders_path": filepath})
    # L'interface affiche le chemin du fichier OMS généré


# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  POST /api/sector-segmentation — SEGMENTATION SECTORIELLE EN TEMPS RÉEL   │
# │  Retourne la segmentation sectorielle selon le profil de risque.           │
# │  Appelé pendant que le PM remplit le formulaire (pas besoin de run).      │
# └─────────────────────────────────────────────────────────────────────────────┘

@app.route("/api/sector-segmentation", methods=["POST"])
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


# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  GET /api/health — HEALTH CHECK                                             │
# │  Utilisé pour vérifier que l'API est bien démarrée (ex: start.bat).       │
# └─────────────────────────────────────────────────────────────────────────────┘

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "version": "2.1"})
    # L'interface vérifie cette route au chargement pour confirmer que l'API répond


# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  GET /api/quotes?tickers=NVDA,MSFT,... — COURS DE BOURSE (onglet Marché)   │
# │  Utilise tools.market_data.get_stock_info (cache 30 min, fallback FMP).    │
# │  Renvoie une liste de quotes : prix, capitalisation, beta, 52w range, etc. │
# └─────────────────────────────────────────────────────────────────────────────┘

@app.route("/api/quotes", methods=["GET"])
def get_quotes():
    """
    Cours de bourse pour un ou plusieurs tickers.
    Query param : ?tickers=NVDA,MSFT,LLY  (séparés par des virgules)
    Données via tools.market_data (yfinance → fallback FMP, cache LRU 30 min).
    """
    import re as _re
    from tools.market_data import get_stock_info, get_price_history

    raw = request.args.get("tickers", "").strip()
    if not raw:
        return jsonify({"error": "Paramètre 'tickers' requis"}), 400

    # Découpe + sanitisation (max 20 tickers par appel pour limiter la charge)
    tickers = [t.strip().upper() for t in raw.split(",") if t.strip()][:20]
    valid = [t for t in tickers if _re.match(r'^[A-Z0-9.\-^]{1,12}$', t)]

    def _clean(x):
        # Neutralise NaN/inf venant de yfinance (sinon JSON invalide / affichage cassé)
        if isinstance(x, float) and (x != x or x in (float("inf"), float("-inf"))):
            return None
        return x

    def _quote_one(tk):
        # Travail complet pour UN ticker (info + historique). Isolé pour être
        # parallélisable : chaque ticker = 2 requêtes réseau indépendantes.
        info = get_stock_info(tk)
        if info.get("statut") != "OK":
            return {
                "ticker":  tk,
                "statut":  "ERREUR",
                "message": info.get("message", "Données indisponibles"),
            }
        # Performance YTD-ish (1 an) via l'historique (déjà caché)
        perf = None
        hist = get_price_history(tk, period="1y")
        if hist.get("statut") == "OK":
            perf = hist.get("performance_periode")
            # yfinance peut renvoyer NaN → casse le JSON. On neutralise en None.
            if perf is not None and perf != perf:  # NaN != NaN
                perf = None
        prix = _clean(info.get("prix_actuel"))
        bas  = _clean(info.get("semaine_52_bas"))
        haut = _clean(info.get("semaine_52_haut"))
        # Position dans la fourchette 52 semaines (0 = au plus bas, 1 = au plus haut)
        pos_52w = None
        if prix and bas and haut and haut > bas:
            pos_52w = round((prix - bas) / (haut - bas), 4)
        return {
            "ticker":          tk,
            "nom":             info.get("nom"),
            "secteur":         info.get("secteur"),
            "pays":            info.get("pays"),
            "devise":          info.get("devise", "USD"),
            "prix":            prix,
            "capitalisation_mrd": _clean(info.get("capitalisation_mrd_usd")),
            "beta":            _clean(info.get("beta")),
            "semaine_52_bas":  bas,
            "semaine_52_haut": haut,
            "position_52w":    pos_52w,
            "volume_moyen_30j": _clean(info.get("volume_moyen_30j")),
            "perf_1an":        perf,
            "source":          info.get("_source", "?"),
            "statut":          "OK",
        }

    # Parallélisation I/O-bound : N tickers = N×2 requêtes réseau. En séquentiel,
    # 5 tickers ≈ 10 s ; avec 8 workers ≈ 1,5 s. L'ordre des résultats est
    # préservé par executor.map. Un ticker en échec n'affecte pas les autres.
    from concurrent.futures import ThreadPoolExecutor
    if len(valid) > 1:
        with ThreadPoolExecutor(max_workers=min(8, len(valid))) as ex:
            quotes = list(ex.map(_quote_one, valid))
    else:
        quotes = [_quote_one(tk) for tk in valid]

    return jsonify({
        "quotes":   quotes,
        "horodatage": datetime.utcnow().isoformat() + "Z",
        "note":     "Données quasi temps réel (cache 30 min, source yfinance/FMP).",
    })


# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  GET /api/quotes/live?tickers=NVDA,MSFT — COURS LIVE (polling rapide)      │
# │  Contourne le cache 30 min. Utilise yf.Ticker.fast_info (endpoint léger    │
# │  Yahoo, conçu pour le prix). Appelé par l'auto-refresh frontend (~8s).     │
# │  Renvoie last_price + previous_close → la variation du jour est calculable.│
# └─────────────────────────────────────────────────────────────────────────────┘

@app.route("/api/quotes/live", methods=["GET"])
def get_quotes_live():
    """
    Cours LIVE (pas de cache) pour l'auto-refresh de l'onglet Marché.
    fast_info de yfinance = endpoint Yahoo léger, rapide, pensé pour le prix.
    Tolérant aux pannes : un ticker en échec n'invalide pas les autres.
    """
    import re as _re
    import yfinance as yf

    raw = request.args.get("tickers", "").strip()
    if not raw:
        return jsonify({"error": "Paramètre 'tickers' requis"}), 400

    tickers = [t.strip().upper() for t in raw.split(",") if t.strip()][:20]
    valid = [t for t in tickers if _re.match(r'^[A-Z0-9.\-^]{1,12}$', t)]

    def _num(x):
        # NaN/inf/None → None (JSON propre)
        try:
            x = float(x)
        except (TypeError, ValueError):
            return None
        if x != x or x in (float("inf"), float("-inf")):
            return None
        return x

    def _live_one(tk):
        try:
            fi = yf.Ticker(tk).fast_info
            last = _num(fi["last_price"])
            prev = _num(fi["previous_close"])
            if last is None:
                return {"ticker": tk, "statut": "ERREUR", "message": "Prix indisponible"}
            # Variation du jour (vs clôture précédente)
            var_abs = var_pct = None
            if prev not in (None, 0):
                var_abs = round(last - prev, 4)
                var_pct = round((last - prev) / prev, 6)
            return {
                "ticker":         tk,
                "prix":           last,
                "cloture_prec":   prev,
                "variation_abs":  var_abs,
                "variation_pct":  var_pct,
                "ouverture":      _num(fi["open"]),
                "haut_jour":      _num(fi["day_high"]),
                "bas_jour":       _num(fi["day_low"]),
                "annee_haut":     _num(fi["year_high"]),
                "annee_bas":      _num(fi["year_low"]),
                "volume":         _num(fi["last_volume"]),
                "devise":         (fi["currency"] or "USD"),
                "statut":         "OK",
            }
        except Exception as e:
            return {"ticker": tk, "statut": "ERREUR", "message": str(e)[:80]}

    # Endpoint pollé toutes les ~8 s par l'onglet Marché : la latence perçue est
    # celle du ticker le plus lent, pas la somme → parallélisation I/O.
    from concurrent.futures import ThreadPoolExecutor
    if len(valid) > 1:
        with ThreadPoolExecutor(max_workers=min(8, len(valid))) as ex:
            quotes = list(ex.map(_live_one, valid))
    else:
        quotes = [_live_one(tk) for tk in valid]

    return jsonify({
        "quotes":     quotes,
        "horodatage": datetime.utcnow().isoformat() + "Z",
        "note":       "Cours live (fast_info Yahoo, sans cache). Peut être différé selon la place.",
    })


# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  GET /api/report/<ticker> — RAPPORT HTML PAR TICKER                        │
# │  Sert le dernier rapport HTML généré pour un ticker par EquityResearch.   │
# └─────────────────────────────────────────────────────────────────────────────┘

@app.route("/api/report/<path:ticker>")
def get_report(ticker: str):
    """
    Sert le dernier rapport HTML généré pour un ticker.
    Le ticker est url-encodé (ex: SAN.PA → SAN.PA, 7203.T → 7203.T).
    Cherche outputs/research/{ticker}_report_*.html → retourne le plus récent.
    """
    import re as _re
    import glob as _glob
    # Sanitisation : bloque les path traversal (../ ou caractères dangereux)
    if not _re.match(r'^[A-Za-z0-9.\-_]+$', ticker):
        return jsonify({"error": "Ticker invalide"}), 400
    research_dir = os.path.join(settings.OUTPUTS_DIR, "research")

    # ── Recherche du rapport le plus récent ───────────────────────────────────
    pattern = os.path.join(research_dir, f"{ticker}_report_*.html")
    files = sorted(_glob.glob(pattern), reverse=True)
    # sorted(..., reverse=True) : le fichier le plus récent en premier
    # Ex: ["outputs/research/NVDA_report_20260329.html", "NVDA_report_20260328.html"]

    if not files:
        # ── Fallback : rapport sans date ──────────────────────────────────────
        pattern2 = os.path.join(research_dir, f"{ticker}_*.html")
        files = sorted(_glob.glob(pattern2), reverse=True)

    if not files:
        # ── 404 personnalisée ─────────────────────────────────────────────────
        return (
            f"<html><body style='font-family:sans-serif;background:#05080f;color:#eef0f7;padding:40px'>"
            f"<h2>Rapport introuvable</h2><p>Aucun rapport HTML pour {ticker}.</p>"
            f"<p>Assurez-vous que l'agent Equity Research a bien tourné.</p></body></html>"
        ), 404

    filepath = files[0]
    return send_from_directory(
        os.path.dirname(os.path.abspath(filepath)),
        # Dossier absolu contenant le fichier (requis par send_from_directory)
        os.path.basename(filepath)
        # Nom du fichier seul (ex: "NVDA_report_20260329.html")
    )


# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  GET /api/sector-report/<sector> — RAPPORT HTML SECTORIEL                  │
# │  Sert le dernier rapport sectoriel généré par EquityResearchAgent.        │
# └─────────────────────────────────────────────────────────────────────────────┘

@app.route("/api/sector-report/<path:sector>")
def get_sector_report(sector: str):
    """
    Sert le dernier rapport HTML sectoriel généré pour un secteur.
    Le secteur est url-encodé (ex: Santé → Santé → slug sante).
    Cherche outputs/research/sector_{slug}_*.html → retourne le plus récent.
    """
    import glob as _glob
    import unicodedata as _ud
    import re as _re
    # Sanitisation : bloque les path traversal
    if '..' in sector or '/' in sector or '\\' in sector:
        return jsonify({"error": "Secteur invalide"}), 400

    # ── Slugification du nom de secteur ───────────────────────────────────────
    # "Santé" → "sante", "Information Technology" → "information_technology"
    # Nécessaire car les noms de fichiers ne peuvent pas contenir d'accents ou espaces.
    def _slug(name: str) -> str:
        nfkd     = _ud.normalize('NFKD', name)           # Décompose les caractères accentués
        ascii_str = nfkd.encode('ascii', 'ignore').decode('ascii')  # Supprime les accents
        return _re.sub(r'[^a-z0-9]+', '_', ascii_str.lower()).strip('_') or 'autre'
        # Remplace tout ce qui n'est pas alphanumérique par "_"

    slug         = _slug(sector)
    research_dir = os.path.join(settings.OUTPUTS_DIR, "research")
    pattern      = os.path.join(research_dir, f"sector_{slug}_*.html")
    files        = sorted(_glob.glob(pattern), reverse=True)

    if not files:
        return (
            f"<html><body style='font-family:sans-serif;background:#05080f;color:#eef0f7;padding:40px'>"
            f"<h2>Rapport sectoriel introuvable</h2>"
            f"<p>Aucun rapport HTML pour le secteur "
            f"<strong>{_html.escape(sector)}</strong>.</p>"
            f"<p>Assurez-vous que l'agent Equity Research a bien tourné.</p>"
            f"</body></html>"
        ), 404

    filepath = files[0]
    return send_from_directory(
        os.path.dirname(os.path.abspath(filepath)),
        os.path.basename(filepath)
    )


# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  GET / — LANDING PAGE SCROLL-DRIVEN                                         │
# │  La route racine sert la landing animée (landing/index.html).              │
# │  L'interface principale est accessible via /app.                            │
# └─────────────────────────────────────────────────────────────────────────────┘

@app.route("/")
def index():
    return send_from_directory("landing", "index.html")


@app.route("/app")
def app_interface():
    """Interface principale AlphaSwarm (anciennement servie sur /)."""
    return send_from_directory(".", "finagent_full_interface.html")


@app.route("/landing/<path:filepath>")
def landing_assets(filepath):
    """Sert les assets de la landing : css/, js/, frames/."""
    return send_from_directory("landing", filepath)


@app.route("/vendor/<path:filepath>")
def vendor_assets(filepath):
    """Sert les libs JS locales (ex: three.min.js) téléchargées dans vendor/."""
    return send_from_directory("vendor", filepath)


# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  HELPERS CHAT — synthèse du mandat et de la recherche pour les agents       │
# │  Partagés par /api/chat et /api/portfolio/briefing pour que TOUS les chats  │
# │  de l'agent portefeuille connaissent le mandat créé par l'Agent Mandats.    │
# └─────────────────────────────────────────────────────────────────────────────┘

def _mandate_summary(mandate: dict) -> dict:
    """
    Construit un résumé COMPLET du mandat pour le prompt système d'un chat.
    `mandate` est le dict sérialisé (tel que renvoyé par _serialize / model_dump).
    On expose tous les champs dont un Portfolio Manager a besoin pour dialoguer
    sans rien redemander : profil, horizon, univers, contraintes, budget risque, ESG.
    """
    if not mandate:
        return {}

    budget = mandate.get("budget_risque") or {}
    contraintes = mandate.get("contraintes_sectorielles") or {}
    # On ne garde que secteur -> max pour rester compact (les clés disent déjà l'univers sectoriel).
    contraintes_compact = {}
    for sect, lim in contraintes.items():
        if isinstance(lim, dict):
            contraintes_compact[sect] = lim.get("max")
        else:
            contraintes_compact[sect] = lim

    return {
        "strategie":              mandate.get("strategie"),
        "benchmark":              mandate.get("benchmark"),
        "horizon":                mandate.get("horizon"),
        "capital":                mandate.get("capital"),
        "profil_risque":          mandate.get("profil_risque_effectif") or mandate.get("profil_risque"),
        "priorite":               mandate.get("priorite_principale"),
        "univers":                mandate.get("univers"),
        "poids_max_par_position": mandate.get("poids_max_par_position"),
        "poids_min_par_position": mandate.get("poids_min_par_position"),
        "nombre_positions_cible": mandate.get("nombre_positions_cible"),
        "cash_min":               mandate.get("cash_min"),
        "cash_max":               mandate.get("cash_max"),
        "limite_turnover":        mandate.get("limite_turnover"),
        "frequence_rebalancement": mandate.get("frequence_rebalancement"),
        "contraintes_sectorielles_max": contraintes_compact,
        "criteres_ESG":           mandate.get("criteres_ESG"),
        "actifs_exclus":          mandate.get("actifs_exclus"),
        "budget_risque": {
            "beta_min":            budget.get("beta_min"),
            "beta_max":            budget.get("beta_max"),
            "volatilite_max":      budget.get("volatilite_max"),
            "tracking_error_max":  budget.get("tracking_error_max"),
            "drawdown_max":        budget.get("drawdown_max"),
        },
    }


def _buy_list(research) -> list:
    """Extrait la liste compacte des titres recommandés BUY depuis la recherche."""
    buy = []
    for r in (research or []):
        if not isinstance(r, dict):
            continue
        if r.get("recommandation") == "BUY":
            buy.append({
                "ticker":  r.get("ticker"),
                "nom":     r.get("nom"),
                "secteur": r.get("secteur"),
                "score":   r.get("score_conviction"),
                "these":   (r.get("these_investissement") or "")[:160],
            })
    return buy


# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  POST /api/chat — CHAT AVEC UN AGENT INDIVIDUEL                             │
# │  Permet d'interroger un agent précis (research, portfolio, risk, execution) │
# │  avec un historique de messages et un contexte du run courant.             │
# └─────────────────────────────────────────────────────────────────────────────┘

@app.route("/api/chat", methods=["POST"])
def chat():
    """
    Endpoint de chat pour les agents individuels.
    Body: { "agent": "research|portfolio|risk|execution", "messages": [...], "context": {...} }
    """
    from llm.client import get_client
    chat_provider = settings.resolve_provider("chat")
    chat_model    = settings.resolve_model("chat")

    data = request.get_json() or {}
    agent_name = data.get("agent", "research")
    messages = data.get("messages", [])
    context = data.get("context", {})

    # System prompts par agent
    system_prompts = {
        "research": """Tu es un analyste equity senior (buy-side). Tu as accès aux résultats d'analyse du portefeuille.
Réponds de façon précise, professionnelle et actionnables. Cite des métriques concrètes.
Contexte actuel : {context}""",
        "portfolio": """Tu es un Portfolio Manager senior. Tu assistes dans la construction et l'optimisation du portefeuille.
Propose des ajustements concrets, chiffrés, cohérents avec les contraintes du mandat.
Contexte actuel : {context}""",
        "risk": """Tu es un Risk Manager institutionnel. Tu analyses les risques du portefeuille et proposes des actions correctives.
Utilise des métriques précises (VaR, volatilité, beta, tracking error, drawdown).
Contexte actuel : {context}""",
        "execution": """Tu es un trader/desk d'exécution institutionnel. Tu optimises l'exécution des ordres.
Considère la liquidité, le slippage, les coûts de transaction, le timing optimal.
Contexte actuel : {context}"""
    }

    system = system_prompts.get(agent_name, system_prompts["research"])

    # ── Contexte injecté dans le prompt système ───────────────────────────────
    # On met EN PREMIER le mandat (créé par l'Agent Mandats) pour que l'agent
    # connaisse profil, horizon, univers, contraintes, budget risque et ESG —
    # et n'ait jamais à les redemander. Vient ensuite la liste BUY (pour le PM)
    # puis le reste de l'état (portfolio/risk/execution) si présent.
    ctx_parts = []
    mandate_ctx = _mandate_summary(context.get("mandate") or {})
    if mandate_ctx:
        ctx_parts.append(
            "MANDAT EN VIGUEUR (déjà décidé par l'Agent Mandats — appuie-toi dessus, "
            "ne redemande PAS ce qui y figure) : "
            + json.dumps(mandate_ctx, ensure_ascii=False)
        )
    if agent_name in ("portfolio", "risk", "execution"):
        buy_list = _buy_list(context.get("research"))
        if buy_list:
            ctx_parts.append(
                f"TITRES BUY DISPONIBLES ({len(buy_list)}) : "
                + json.dumps(buy_list, ensure_ascii=False)[:3000]
            )
    # Reste de l'état courant (portefeuille construit, risque, exécution).
    # Le client envoie désormais un RÉSUMÉ (positions réduites à ticker/nom/
    # secteur/poids, métriques et violations de risque, volumétrie d'exécution)
    # et non plus l'état complet : ~3,5 Ko pour un portefeuille de 30 lignes,
    # contre ~68 Ko auparavant. L'ancien plafond de 2500 caractères datait de
    # cette époque et coupait le JSON en plein milieu ; il est relevé pour
    # laisser passer le résumé entier tout en gardant un garde-fou contre un
    # client anormal.
    other_ctx = {k: v for k, v in context.items() if k not in ("mandate", "research")}
    if other_ctx:
        ctx_parts.append("ÉTAT COURANT : " + json.dumps(other_ctx, ensure_ascii=False, default=str)[:12000])

    system = system.replace("{context}", "\n\n".join(ctx_parts) if ctx_parts else "Aucun contexte de run disponible pour l'instant.")

    if not messages:
        return jsonify({"error": "messages requis"}), 400

    try:
        client = get_client(provider=chat_provider)
        response = client.messages.create(
            model=chat_model,
            max_tokens=4096,  # large : gpt-oss-20b consomme des tokens de raisonnement
                              # (comptés dans max_tokens) → un budget trop bas tronque
                              # ou vide la réponse. 4096 laisse la place à reasoning + réponse.
            system=system,
            messages=messages
        )
        return jsonify({
            "reply": response.content[0].text,
            "agent": agent_name
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  POST /api/portfolio/briefing — CHAT AVEC LE PM AVANT CONSTRUCTION         │
# │  Permet au gérant de dialoguer avec le Portfolio Manager AVANT que ce       │
# │  dernier ne construise le portefeuille (niveau 3 d'interaction).            │
# │  Body : { "messages": [...], "context": { "mandate": ..., "research": [...] } }
# │  Retourne : { "reply": "..." }                                              │
# └─────────────────────────────────────────────────────────────────────────────┘

@app.route("/api/portfolio/briefing", methods=["POST"])
def portfolio_briefing():
    """
    Chat conversationnel avec le Portfolio Manager Agent AVANT la construction.
    Le PM (utilisateur) peut écarter des titres, demander un style de portefeuille,
    poser des questions sur les BUY de la recherche, etc.
    Le LLM répond sans construire — il dialogue.
    """
    from llm.client import get_client
    chat_provider = settings.resolve_provider("chat")
    chat_model    = settings.resolve_model("chat")

    data = request.get_json() or {}
    messages = data.get("messages", [])
    context = data.get("context", {})

    if not messages:
        return jsonify({"error": "messages requis"}), 400

    # ── Synthèse COMPLÈTE du contexte pour le prompt système ──────────────────
    # On réutilise les helpers partagés avec /api/chat pour que l'agent connaisse
    # tout le mandat (profil, horizon, univers, contraintes, budget risque, ESG).
    mandate_summary = _mandate_summary(context.get("mandate") or {})
    buy_list = _buy_list(context.get("research"))

    benchmark_name = (mandate_summary or {}).get("benchmark") or "le benchmark du mandat"

    system = (
        "Tu es un Portfolio Manager senior DANS l'application AlphaSwarm (tu ES l'outil, "
        "pas un humain externe). Tu dialogues avec le gérant pour CADRER le portefeuille "
        "avant sa construction.\n"
        "\n"
        "RÈGLE N°1 — NE JAMAIS INVENTER D'INTERFACE.\n"
        "Tu ne connais PAS de menus, d'onglets, de boutons d'import. N'utilise JAMAIS les "
        "mots 'onglet', 'Watchlist', 'Buy List', 'importer une liste', 'charger l'univers', "
        "'support technique', 'équipe technique'. Le gérant n'a AUCUNE liste à fournir ni à "
        "saisir : c'est FAUX et tu induirais le gérant en erreur. Le SEUL bouton qui existe "
        "est 'Construire le portefeuille'.\n"
        "\n"
        "COMMENT LES TITRES ARRIVENT (le système le fait tout seul, automatiquement) :\n"
        f"le système lit la composition réelle du benchmark ({benchmark_name}) sur le web, "
        "valide les titres, les filtre selon le mandat ET selon CETTE conversation, puis les "
        "analyse. Tu n'as donc PAS besoin d'une liste : elle se génère seule à la construction.\n"
        "Si le gérant demande 'où est la liste / d'où viennent les titres' : réponds "
        f"EXACTEMENT que les titres sont tirés automatiquement du benchmark ({benchmark_name}) "
        "au moment de la construction, qu'il n'a rien à saisir, et qu'il peut juste te donner "
        "des DIRECTIVES (secteurs à éviter, biais, nombre de positions) que tu transmettras.\n"
        "\n"
        "TON RÔLE : recueillir des directives de cadrage (secteurs à éviter/surpondérer, "
        "biais défensif/croissance, nombre de positions), défier les incohérences avec le "
        "mandat, citer les chiffres du mandat pour argumenter. Concis : 3-4 lignes.\n"
        "\n"
        "NE CITE PAS de tickers précis sortis de ton imagination (pas de 'ASML, SAP...' au "
        "hasard) : les titres réels viennent du benchmark via le système. Discute SECTEURS, "
        "STYLES et BIAIS, pas des noms inventés.\n"
        "\n"
        "INTERDICTION : tu ne construis PAS le portefeuille ici (pas de liste de positions "
        "avec poids, pas de tableau de répartition final). Si on te demande de construire, "
        "renvoie au bouton 'Construire le portefeuille'.\n"
        "\n"
        "Tu CONNAIS déjà le mandat ci-dessous — ne redemande jamais ce qui y figure.\n"
        "\n"
        f"MANDAT EN VIGUEUR : {json.dumps(mandate_summary, ensure_ascii=False) if mandate_summary else 'Non disponible'}\n"
        f"\nTITRES DÉJÀ ANALYSÉS ({len(buy_list)}) : "
        + (json.dumps(buy_list, ensure_ascii=False)[:3500] if buy_list else
           "aucun encore — c'est ATTENDU à ce stade : l'analyse des titres du benchmark se "
           "lancera à la construction. Ce n'est PAS un problème à résoudre, ne demande PAS de "
           "charger quoi que ce soit, n'invente pas de titres. Concentre-toi sur le cadrage "
           "(secteurs, biais, contraintes).")
    )

    try:
        client = get_client(provider=chat_provider)
        response = client.messages.create(
            model=chat_model,
            max_tokens=4096,  # large : gpt-oss-20b consomme des tokens de raisonnement
                              # (comptés dans max_tokens) → un budget trop bas tronque
                              # ou vide la réponse. 4096 laisse la place à reasoning + réponse.
            system=system,
            messages=messages
        )
        return jsonify({
            "reply": response.content[0].text,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  GET /api/research/skills — CATALOGUE DES SKILLS DE RECHERCHE              │
# │  Retourne la liste des skills disponibles (id, label, icon, description).   │
# └─────────────────────────────────────────────────────────────────────────────┘

@app.route("/api/research/skills", methods=["GET"])
def research_skills_list():
    """Liste des skills de research disponibles (pour le menu UI)."""
    from config.research_skills import list_skills
    return jsonify({"skills": list_skills()})


# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  GET /api/research/skill/<skill_id> — DÉTAIL D'UN SKILL                    │
# │  Retourne les questions du wizard pour un skill donné.                      │
# └─────────────────────────────────────────────────────────────────────────────┘

@app.route("/api/research/skill/<skill_id>", methods=["GET"])
def research_skill_detail(skill_id):
    """Retourne le détail d'un skill (questions du wizard)."""
    from config.research_skills import get_skill
    skill = get_skill(skill_id)
    if not skill:
        return jsonify({"error": f"Skill '{skill_id}' inconnu"}), 404
    # On expose tout sauf le prompt système (réservé au backend)
    return jsonify({
        "id":          skill_id,
        "label":       skill["label"],
        "icon":        skill["icon"],
        "tagline":     skill["tagline"],
        "description": skill["description"],
        "questions":   skill["questions"],
    })


# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  POST /api/research/skill/<skill_id>/run — EXÉCUTE UN SKILL                │
# │  Body : { "answers": {q_id: value, ...}, "context": {...} }                │
# │  Retourne : { "markdown": "...", "exports": {excel, word, pptx urls} }     │
# └─────────────────────────────────────────────────────────────────────────────┘

@app.route("/api/research/skill/<skill_id>/run", methods=["POST"])
def research_skill_run(skill_id):
    """
    Exécute un skill de research avec les réponses du wizard.
    Génère l'analyse Markdown + les exports Excel/Word/PowerPoint.
    """
    from config.research_skills import get_skill
    from llm.client import get_client
    from tools.research_export import (
        export_skill_to_excel,
        export_skill_to_word,
        export_skill_to_pptx,
    )

    skill = get_skill(skill_id)
    if not skill:
        return jsonify({"error": f"Skill '{skill_id}' inconnu"}), 404

    data = request.get_json() or {}
    answers = data.get("answers", {})
    context = data.get("context", {})

    # Validation : toutes les questions required doivent avoir une réponse
    missing = []
    for q in skill["questions"]:
        if q.get("required"):
            v = answers.get(q["id"])
            if v in (None, "", []):
                missing.append(q["label"])
    if missing:
        return jsonify({"error": f"Champs requis manquants : {', '.join(missing)}"}), 400

    # ── Construction du user message à partir des réponses ────────────────────
    user_msg_parts = [f"=== {skill['label']} ===\n"]
    for q in skill["questions"]:
        v = answers.get(q["id"])
        if v in (None, "", []):
            continue
        if isinstance(v, list):
            v = ", ".join(str(x) for x in v)
        user_msg_parts.append(f"{q['label']} : {v}")

    # Contexte mandat si disponible
    mandate = context.get("mandate") or {}
    if mandate:
        user_msg_parts.append("\n\nMANDAT ACTIF :")
        for k in ("profil_risque", "profil_risque_effectif", "horizon", "capital",
                  "priorite_principale", "nombre_positions_cible"):
            if mandate.get(k):
                user_msg_parts.append(f"- {k} : {mandate[k]}")

    user_msg = "\n".join(user_msg_parts)

    # ── Provider/modèle pour le skill (via override LLM_PROVIDER_RESEARCH) ────
    provider = settings.resolve_provider("research")
    model    = settings.resolve_model("research")

    try:
        client = get_client(provider=provider)
        response = client.messages.create(
            model=model,
            # Les system_prompt des skills demandent 3 000 à 7 000 mots : à
            # 4 000 tokens la sortie était structurellement tronquée (défaut C11).
            max_tokens=16000,
            system=skill["system_prompt"],
            messages=[{"role": "user", "content": user_msg}],
        )
        markdown = response.content[0].text if response.content else ""

        # ── Génération des exports ────────────────────────────────────────────
        out_dir = os.path.join(settings.OUTPUTS_DIR, "research_exports")
        Path(out_dir).mkdir(parents=True, exist_ok=True)

        skill_meta = {
            "id":             skill_id,
            "label":          skill["label"],
            "filename_prefix": skill.get("output_filename_prefix", "Research"),
            "answers":        answers,
        }

        exports = {}
        try:
            xls = export_skill_to_excel(markdown, skill_meta, out_dir)
            exports["excel"] = {
                "filename": os.path.basename(xls),
                "url":      f"/api/research/export/file/{os.path.basename(xls)}",
            }
        except Exception as e:
            exports["excel"] = {"error": str(e)}
        try:
            doc = export_skill_to_word(markdown, skill_meta, out_dir)
            exports["word"] = {
                "filename": os.path.basename(doc),
                "url":      f"/api/research/export/file/{os.path.basename(doc)}",
            }
        except Exception as e:
            exports["word"] = {"error": str(e)}
        try:
            ppt = export_skill_to_pptx(markdown, skill_meta, out_dir)
            exports["pptx"] = {
                "filename": os.path.basename(ppt),
                "url":      f"/api/research/export/file/{os.path.basename(ppt)}",
            }
        except Exception as e:
            exports["pptx"] = {"error": str(e)}

        return jsonify({
            "skill":    skill_id,
            "markdown": markdown,
            "exports":  exports,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  POST /api/research/briefing — BRIEFING CONVERSATIONNEL DYNAMIQUE          │
# │  L'agent pose des questions guidées au PM AVANT de lancer la recherche.    │
# │  Les questions sont GÉNÉRÉES par le LLM (pas hardcodées) selon contexte.   │
# │  Body : { "messages": [...], "context": { "mandate": ... } }                │
# │  Retourne un objet structuré : {type, message, options, allow_free_text,    │
# │                                  brief_so_far, conflit_mandat}              │
# └─────────────────────────────────────────────────────────────────────────────┘

@app.route("/api/research/briefing", methods=["POST"])
def research_briefing():
    """
    Briefing conversationnel pour le PM avant la recherche equity.
    Le LLM analyse l'historique, identifie ce qui manque, et génère :
      - une question avec options cliquables (chips), OU
      - un avertissement si réponse incompatible avec le mandat, OU
      - un récap final (type=ready) pour lancer la recherche.
    """
    from llm.client import get_client
    chat_provider = settings.resolve_provider("chat")
    chat_model    = settings.resolve_model("chat")

    data = request.get_json() or {}
    messages = data.get("messages", [])
    context  = data.get("context", {})

    # ── Synthèse du mandat pour orienter les questions ────────────────────────
    mandate = context.get("mandate") or {}
    mandate_summary = {
        "profil_risque":          mandate.get("profil_risque_effectif") or mandate.get("profil_risque"),
        "priorite":               mandate.get("priorite_principale"),
        "horizon":                mandate.get("horizon"),
        "univers_admissibles":    mandate.get("univers"),
        "contraintes_sect_keys":  list((mandate.get("contraintes_sectorielles") or {}).keys())[:8],
        "nombre_positions_cible": mandate.get("nombre_positions_cible"),
    }

    # ── Prompt système : le LLM doit retourner du JSON strict ─────────────────
    system = (
        "Tu es un Equity Research Lead senior. Ta mission ICI est de QUESTIONNER "
        "le Portfolio Manager pour cadrer une recherche d'idées d'investissement, "
        "PAS de produire l'analyse.\n\n"
        "PROCESSUS :\n"
        " 1. Lis la requête initiale du PM\n"
        " 2. Identifie les paramètres MANQUANTS (long/short, univers, secteur, style, "
        "    taille de capi, géographie, nombre d'idées, contraintes additionnelles)\n"
        " 3. Pose UNE question à la fois avec 3-7 options cliquables pertinentes\n"
        " 4. Si une réponse contredit le mandat (ex: profil conservateur + "
        "    croissance agressive), avertis CLAIREMENT en proposant 3 options : "
        "    'Confirmer ce choix', 'Reformuler', 'Rester dans le mandat'\n"
        " 5. Quand tu as assez d'info (au moins long/short + univers + style + capi + géo + nb), "
        "    retourne type='ready' avec le récap dans brief_so_far\n\n"
        "FORMAT DE RÉPONSE (JSON STRICT, RIEN D'AUTRE) :\n"
        "{\n"
        '  "type": "question" | "warning" | "ready",\n'
        '  "message": "ta question ou ton récap (français, court, direct)",\n'
        '  "options": ["option 1", "option 2", ...],   // chips cliquables, peut être vide\n'
        '  "allow_free_text": true,\n'
        '  "brief_so_far": {                           // état progressif du brief\n'
        '     "requete_initiale": "...",\n'
        '     "long_short": "long" | "short" | "long_short_pair" | null,\n'
        '     "univers": "tech" | "sante" | "finance" | "energie" | "industrie" | "conso" | "multi" | null,\n'
        '     "sous_secteur": "..." | null,\n'
        '     "style": "value" | "garp" | "growth" | "quality" | "momentum" | "dislocation" | null,\n'
        '     "taille_capi": "mega" | "large" | "mid" | "small" | "micro" | null,\n'
        '     "geo": "us" | "europe" | "asia_ex_china" | "china_hk" | "global_dm" | "em" | null,\n'
        '     "nb_idees": int | null,\n'
        '     "contraintes": "...",\n'
        '     "tickers_focus": [...]  // si le PM cite des tickers précis\n'
        "  },\n"
        '  "conflit_mandat": "description courte si conflit, sinon null"\n'
        "}\n\n"
        f"MANDAT EN VIGUEUR : {json.dumps(mandate_summary, ensure_ascii=False)}\n\n"
        "Style : pas d'emoji, phrases courtes, ton direct. Si la requête initiale est "
        "très précise, tu peux passer directement à 'ready'. Si elle est vague, "
        "questionne pas à pas."
    )

    if not messages:
        return jsonify({"error": "messages requis"}), 400

    try:
        client = get_client(provider=chat_provider)
        response = client.messages.create(
            model=chat_model,
            max_tokens=4096,  # large : gpt-oss-20b consomme des tokens de raisonnement
                              # (comptés dans max_tokens) → un budget trop bas tronque
                              # ou vide la réponse. 4096 laisse la place à reasoning + réponse.
            system=system,
            messages=messages
        )
        raw = response.content[0].text or ""
        # Extraction JSON tolérante (le modèle peut entourer de texte ou de markdown)
        text = raw.strip()
        if "```" in text:
            # Bloc markdown : on prend ce qui est entre les backticks
            parts = text.split("```")
            for part in parts:
                p = part.strip()
                if p.startswith("json"):
                    p = p[4:].strip()
                if p.startswith("{"):
                    text = p
                    break
        # Sinon on cherche le premier { jusqu'au dernier }
        if not text.startswith("{"):
            s = text.find("{")
            e = text.rfind("}")
            if s != -1 and e > s:
                text = text[s:e + 1]
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = {
                "type": "question",
                "message": raw,
                "options": [],
                "allow_free_text": True,
                "brief_so_far": {},
                "conflit_mandat": None,
            }
        return jsonify(payload)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  POST /api/research/exports/<format> — GÉNÉRATION DES LIVRABLES            │
# │  format ∈ {excel, word, pptx}. Le PDF/HTML existe déjà via chat-report.     │
# │  Body : { "research": [...], "brief": {...} }                              │
# └─────────────────────────────────────────────────────────────────────────────┘

@app.route("/api/research/export/<fmt>", methods=["POST"])
def research_export(fmt):
    """Génère un livrable Research dans le format demandé."""
    from tools.research_export import (
        export_research_to_excel,
        export_research_to_word,
        export_research_to_pptx,
    )
    fmt = (fmt or "").lower()
    data = request.get_json() or {}
    research = data.get("research") or []
    brief    = data.get("brief")    or {}

    if not research:
        return jsonify({"error": "research vide"}), 400

    out_dir = os.path.join(settings.OUTPUTS_DIR, "research_exports")
    Path(out_dir).mkdir(parents=True, exist_ok=True)

    try:
        if fmt == "excel":
            path = export_research_to_excel(research, brief, out_dir)
        elif fmt == "word":
            path = export_research_to_word(research, brief, out_dir)
        elif fmt == "pptx":
            path = export_research_to_pptx(research, brief, out_dir)
        else:
            return jsonify({"error": f"format inconnu: {fmt}"}), 400
        filename = os.path.basename(path)
        return jsonify({
            "filename": filename,
            "url":      f"/api/research/export/file/{filename}",
            "format":   fmt,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/research/export/file/<path:filename>")
def serve_research_export(filename: str):
    """Sert un fichier d'export Research (Excel/Word/PPT)."""
    import re as _re
    if '..' in filename or not _re.match(r'^[A-Za-z0-9._\-]+$', filename):
        return jsonify({"error": "Nom de fichier invalide"}), 400
    out_dir = os.path.join(settings.OUTPUTS_DIR, "research_exports")
    return send_from_directory(os.path.abspath(out_dir), filename, as_attachment=True)


# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  POST /api/chat-report — GÉNÉRATION RAPPORT À LA DEMANDE (depuis le chat)  │
# └─────────────────────────────────────────────────────────────────────────────┘

@app.route("/api/chat-report", methods=["POST"])
def chat_report():
    """
    Génère un rapport HTML + PDF pour un ticker donné.
    Body: { "ticker": "NVDA", "lang": "fr" }
    """
    from tools.chat_report import generate_report
    data   = request.get_json() or {}
    ticker = (data.get("ticker") or "").strip().upper()
    lang   = data.get("lang", "fr")

    if not ticker:
        return jsonify({"error": "ticker requis"}), 400

    result = generate_report(ticker, lang=lang, outputs_dir=settings.OUTPUTS_DIR)
    if result.get("error"):
        return jsonify({"error": result["error"]}), 500

    return jsonify(result)


@app.route("/api/chat-report/file/<path:filename>")
def serve_chat_report_file(filename: str):
    """Sert les fichiers HTML et PDF générés à la demande."""
    import re as _re
    from flask import send_from_directory as _sfd
    # Sanitisation : bloque les path traversal
    if '..' in filename or not _re.match(r'^[A-Za-z0-9._\-]+$', filename):
        return jsonify({"error": "Nom de fichier invalide"}), 400
    report_dir = os.path.join(settings.OUTPUTS_DIR, "chat_reports")
    return _sfd(os.path.abspath(report_dir), filename)


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║  LANCEMENT                                                                  ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

if __name__ == "__main__":
    # ── Point d'entrée : python api.py ────────────────────────────────────────
    # Ce bloc ne s'exécute que si le fichier est lancé directement (pas importé).
    print("AlphaSwarm API démarrée sur http://localhost:5001")
    print("Interface disponible sur http://localhost:5001/")
    app.run(
        host="0.0.0.0",   # Écoute sur toutes les interfaces réseau (LAN + localhost)
        port=5001,        # Port fixe (défini dans l'interface HTML)
        debug=False,      # debug=False : pas de rechargement automatique, plus stable
        threaded=True,    # threaded=True : chaque requête dans son propre thread
                          # Nécessaire pour que le polling fonctionne pendant qu'un
                          # workflow tourne dans un autre thread
    )
