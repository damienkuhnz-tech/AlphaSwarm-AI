"""
WEBAPP / ROUTES / REPORTS — rapports HTML/PDF de la recherche.

GET  /api/report/<ticker>          : dernier rapport HTML d'un titre
GET  /api/sector-report/<secteur>  : dernier rapport HTML sectoriel
POST /api/chat-report              : génération à la demande depuis le chat
GET  /api/chat-report/file/<nom>   : sert les fichiers générés
"""

import os
import html as _html

from flask import Blueprint, request, jsonify, send_from_directory

from config.settings import settings

bp = Blueprint("reports", __name__)

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  GET /api/report/<ticker> — RAPPORT HTML PAR TICKER                        │
# │  Sert le dernier rapport HTML généré pour un ticker par EquityResearch.   │
# └─────────────────────────────────────────────────────────────────────────────┘

@bp.route("/api/report/<path:ticker>")
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

@bp.route("/api/sector-report/<path:sector>")
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
# │  POST /api/chat-report — GÉNÉRATION RAPPORT À LA DEMANDE (depuis le chat)  │
# └─────────────────────────────────────────────────────────────────────────────┘

@bp.route("/api/chat-report", methods=["POST"])
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


@bp.route("/api/chat-report/file/<path:filename>")
def serve_chat_report_file(filename: str):
    """Sert les fichiers HTML et PDF générés à la demande."""
    import re as _re
    from flask import send_from_directory as _sfd
    # Sanitisation : bloque les path traversal
    if '..' in filename or not _re.match(r'^[A-Za-z0-9._\-]+$', filename):
        return jsonify({"error": "Nom de fichier invalide"}), 400
    report_dir = os.path.join(settings.OUTPUTS_DIR, "chat_reports")
    return _sfd(os.path.abspath(report_dir), filename)
