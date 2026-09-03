"""
WEBAPP / RUN STORE - état partagé des runs en mémoire.

Module UNIQUE importé à la fois par les routes (webapp.routes.runs) et par le
service d'exécution (webapp.services.run_service) : le dict _runs et son verrou
doivent être une seule et même instance. TOUJOURS MUTER _runs, jamais le
réassigner (une réassignation casserait le partage entre importeurs).
"""

import threading

_runs: dict = {}
# Dict global : survit entre les requêtes Flask (scope module).
# Contient tous les runs en cours et terminés depuis le démarrage de l'API.
# Ex: {"A3F7B2C1": {"status": "running", "log": [...], ...}}
_MAX_RUNS = 20  # Limite mémoire : on garde les N derniers runs pour éviter une fuite

_runs_lock = threading.Lock()
# Verrou pour accès thread-safe à _runs.
# Nécessaire car : le thread workflow (background) et les requêtes Flask (autre thread)
# lisent/écrivent _runs en même temps. Sans lock → race condition → crash ou données corrompues.

