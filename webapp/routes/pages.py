"""
WEBAPP / ROUTES / PAGES — pages et assets statiques de l'interface.

GET /                  : landing page scroll-driven
GET /app               : interface principale (templates/app.html + partials)
GET /landing|vendor|static/<chemin> : assets

Les chemins sont résolus en ABSOLU contre la racine du projet (BASE_DIR) :
un chemin relatif serait résolu contre le root_path, fragile dans un package.
"""

from pathlib import Path

from flask import Blueprint, render_template, send_from_directory

BASE_DIR = Path(__file__).resolve().parent.parent.parent

bp = Blueprint("pages", __name__)


@bp.route("/")
def index():
    return send_from_directory(BASE_DIR / "landing", "index.html")


@bp.route("/app")
def app_interface():
    """Interface principale AlphaSwarm (templates/app.html + partials par écran)."""
    return render_template("app.html")


@bp.route("/landing/<path:filepath>")
def landing_assets(filepath):
    """Sert les assets de la landing : css/, js/, frames/."""
    return send_from_directory(BASE_DIR / "landing", filepath)


@bp.route("/vendor/<path:filepath>")
def vendor_assets(filepath):
    """Sert les libs JS locales (ex: three.min.js) téléchargées dans vendor/."""
    return send_from_directory(BASE_DIR / "vendor", filepath)


@bp.route("/static/<path:filepath>")
def static_assets(filepath):
    """Sert les assets de l'interface refactorisée : static/css/, static/js/."""
    return send_from_directory(BASE_DIR / "static", filepath)
