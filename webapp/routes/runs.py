"""
WEBAPP / ROUTES / RUNS — cycle de vie d'un run de workflow.

POST /api/run              : démarre un workflow (complet ou agent ciblé)
GET  /api/run/<run_id>     : polling du statut (toutes les 2,5 s côté UI)
POST /api/run/<id>/approve : validation humaine + export OMS
GET  /api/health           : health check
"""

import os
import json
import uuid
import copy
import threading
from datetime import datetime
from pathlib import Path

from flask import Blueprint, request, jsonify

from config.settings import settings
from webapp.run_store import _runs, _runs_lock, _MAX_RUNS
from webapp.services.run_service import _run_workflow_thread

bp = Blueprint("runs", __name__)

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  POST /api/run — DÉMARRAGE D'UN NOUVEAU RUN                                │
# │  Reçoit les paramètres du formulaire HTML → lance le workflow en thread.  │
# └─────────────────────────────────────────────────────────────────────────────┘

@bp.route("/api/run", methods=["POST"])
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

@bp.route("/api/run/<run_id>", methods=["GET"])
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

@bp.route("/api/run/<run_id>/approve", methods=["POST"])
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
# │  GET /api/health — HEALTH CHECK                                             │
# │  Utilisé pour vérifier que l'API est bien démarrée (ex: start.bat).       │
# └─────────────────────────────────────────────────────────────────────────────┘

@bp.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "version": "2.1"})
    # L'interface vérifie cette route au chargement pour confirmer que l'API répond
