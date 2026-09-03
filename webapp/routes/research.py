"""
WEBAPP / ROUTES / RESEARCH - skills de recherche et briefing conversationnel.

GET  /api/research/skills               : catalogue des skills
GET  /api/research/skill/<id>           : questions du wizard d'un skill
POST /api/research/skill/<id>/run       : exécute un skill (analyse + exports)
POST /api/research/briefing             : briefing conversationnel pré-recherche
POST /api/research/export/<fmt>         : génère un livrable (excel/word/pptx)
GET  /api/research/export/file/<nom>    : sert un livrable généré
"""

import os
import json
from pathlib import Path

from flask import Blueprint, request, jsonify, send_from_directory

from config.settings import settings

bp = Blueprint("research", __name__)

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  GET /api/research/skills - CATALOGUE DES SKILLS DE RECHERCHE              │
# │  Retourne la liste des skills disponibles (id, label, icon, description).   │
# └─────────────────────────────────────────────────────────────────────────────┘

@bp.route("/api/research/skills", methods=["GET"])
def research_skills_list():
    """Liste des skills de research disponibles (pour le menu UI)."""
    from config.research_skills import list_skills
    return jsonify({"skills": list_skills()})


# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  GET /api/research/skill/<skill_id> - DÉTAIL D'UN SKILL                    │
# │  Retourne les questions du wizard pour un skill donné.                      │
# └─────────────────────────────────────────────────────────────────────────────┘

@bp.route("/api/research/skill/<skill_id>", methods=["GET"])
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
# │  POST /api/research/skill/<skill_id>/run - EXÉCUTE UN SKILL                │
# │  Body : { "answers": {q_id: value, ...}, "context": {...} }                │
# │  Retourne : { "markdown": "...", "exports": {excel, word, pptx urls} }     │
# └─────────────────────────────────────────────────────────────────────────────┘

@bp.route("/api/research/skill/<skill_id>/run", methods=["POST"])
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
# │  POST /api/research/briefing - BRIEFING CONVERSATIONNEL DYNAMIQUE          │
# │  L'agent pose des questions guidées au PM AVANT de lancer la recherche.    │
# │  Les questions sont GÉNÉRÉES par le LLM (pas hardcodées) selon contexte.   │
# │  Body : { "messages": [...], "context": { "mandate": ... } }                │
# │  Retourne un objet structuré : {type, message, options, allow_free_text,    │
# │                                  brief_so_far, conflit_mandat}              │
# └─────────────────────────────────────────────────────────────────────────────┘

@bp.route("/api/research/briefing", methods=["POST"])
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
# │  POST /api/research/exports/<format> - GÉNÉRATION DES LIVRABLES            │
# │  format ∈ {excel, word, pptx}. Le PDF/HTML existe déjà via chat-report.     │
# │  Body : { "research": [...], "brief": {...} }                              │
# └─────────────────────────────────────────────────────────────────────────────┘

@bp.route("/api/research/export/<fmt>", methods=["POST"])
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


@bp.route("/api/research/export/file/<path:filename>")
def serve_research_export(filename: str):
    """Sert un fichier d'export Research (Excel/Word/PPT)."""
    import re as _re
    if '..' in filename or not _re.match(r'^[A-Za-z0-9._\-]+$', filename):
        return jsonify({"error": "Nom de fichier invalide"}), 400
    out_dir = os.path.join(settings.OUTPUTS_DIR, "research_exports")
    return send_from_directory(os.path.abspath(out_dir), filename, as_attachment=True)
