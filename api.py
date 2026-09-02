"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  ALPHASWARM API — POINT D'ENTRÉE (`python api.py`)                            ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  L'application vit dans le package webapp/ (factory + blueprints) :          ║
║    webapp/__init__.py   create_app (Flask, CORS, blueprints)                 ║
║    webapp/routes/       runs, sector, market, reports, pages, chat, research ║
║    webapp/services/     run_service (thread workflow), chat_service          ║
║    webapp/run_store.py  état partagé des runs                                ║
║                                                                              ║
║  Lancement : python api.py                                                   ║
║  Port      : 5001 (pour ne pas conflicter avec le serveur HTML 7432)         ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import sys
import io

# ── FIX UTF-8 WINDOWS ─────────────────────────────────────────────────────────
# Sur Windows, stdout/stderr utilisent cp1252 par défaut → accents cassés.
# Doit s'exécuter AVANT tout import Flask (les modules loggent à l'import).
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from webapp import create_app

app = create_app()
# Exposé au niveau module : `from api import app` reste possible (tests, WSGI).

if __name__ == "__main__":
    print("AlphaSwarm API démarrée sur http://localhost:5001")
    print("Interface disponible sur http://localhost:5001/")
    app.run(
        host="0.0.0.0",   # Écoute sur toutes les interfaces réseau (LAN + localhost)
        port=5001,        # Port fixe (référencé par l'interface et start.bat)
        debug=False,      # Pas de rechargement automatique, plus stable
        threaded=True,    # Chaque requête dans son thread : le polling continue
                          # de répondre pendant qu'un workflow tourne à côté.
    )
