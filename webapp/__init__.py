"""
WEBAPP - application Flask d'AlphaSwarm (factory + enregistrement des routes).

Découpage issu de la refactorisation d'api.py (1 583 lignes → blueprints) :
  run_store.py            état partagé des runs (dict + lock, instance unique)
  services/run_service.py exécution du workflow en thread
  services/chat_service.py synthèses mandat/recherche pour les chats
  routes/*.py             blueprints par domaine fonctionnel

api.py reste le point d'entrée (`python api.py`) : il applique le fix UTF-8
Windows AVANT d'importer ce package, puis appelle create_app().
"""

import logging
from pathlib import Path

from flask import Flask
from flask_cors import CORS

BASE_DIR = Path(__file__).resolve().parent.parent


def create_app() -> Flask:
    # root_path force la racine du PROJET (et non webapp/) : les templates
    # (templates/), le static_folder ('.') et tout chemin relatif se résolvent
    # exactement comme quand api.py portait l'app - iso-comportement.
    app = Flask(
        "api",
        static_folder=".",
        template_folder="templates",
        root_path=str(BASE_DIR),
    )

    CORS(app, origins=["http://localhost:5001", "http://127.0.0.1:5001"])
    # Restreint aux origines connues pour éviter les requêtes cross-origin malveillantes

    # Silence des logs werkzeug : sans ça, chaque poll (2,5 s) écrit une ligne.
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    from webapp.routes import runs, sector, market, reports, pages, chat, research
    for module in (runs, sector, market, reports, pages, chat, research):
        app.register_blueprint(module.bp)

    return app
