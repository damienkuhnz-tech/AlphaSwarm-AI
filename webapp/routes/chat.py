"""
WEBAPP / ROUTES / CHAT - dialogues avec les agents.

POST /api/chat               : chat avec un agent (research/portfolio/risk/execution)
POST /api/portfolio/briefing : briefing du PM avant construction du portefeuille
"""

import json

from flask import Blueprint, request, jsonify

from config.settings import settings
from webapp.services.chat_service import _mandate_summary, _buy_list

bp = Blueprint("chat", __name__)

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  POST /api/chat - CHAT AVEC UN AGENT INDIVIDUEL                             │
# │  Permet d'interroger un agent précis (research, portfolio, risk, execution) │
# │  avec un historique de messages et un contexte du run courant.             │
# └─────────────────────────────────────────────────────────────────────────────┘

@bp.route("/api/chat", methods=["POST"])
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
    # connaisse profil, horizon, univers, contraintes, budget risque et ESG -
    # et n'ait jamais à les redemander. Vient ensuite la liste BUY (pour le PM)
    # puis le reste de l'état (portfolio/risk/execution) si présent.
    ctx_parts = []
    mandate_ctx = _mandate_summary(context.get("mandate") or {})
    if mandate_ctx:
        ctx_parts.append(
            "MANDAT EN VIGUEUR (déjà décidé par l'Agent Mandats - appuie-toi dessus, "
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
# │  POST /api/portfolio/briefing - CHAT AVEC LE PM AVANT CONSTRUCTION         │
# │  Permet au gérant de dialoguer avec le Portfolio Manager AVANT que ce       │
# │  dernier ne construise le portefeuille (niveau 3 d'interaction).            │
# │  Body : { "messages": [...], "context": { "mandate": ..., "research": [...] } }
# │  Retourne : { "reply": "..." }                                              │
# └─────────────────────────────────────────────────────────────────────────────┘

@bp.route("/api/portfolio/briefing", methods=["POST"])
def portfolio_briefing():
    """
    Chat conversationnel avec le Portfolio Manager Agent AVANT la construction.
    Le PM (utilisateur) peut écarter des titres, demander un style de portefeuille,
    poser des questions sur les BUY de la recherche, etc.
    Le LLM répond sans construire - il dialogue.
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
        "RÈGLE N°1 - NE JAMAIS INVENTER D'INTERFACE.\n"
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
        "Tu CONNAIS déjà le mandat ci-dessous - ne redemande jamais ce qui y figure.\n"
        "\n"
        f"MANDAT EN VIGUEUR : {json.dumps(mandate_summary, ensure_ascii=False) if mandate_summary else 'Non disponible'}\n"
        f"\nTITRES DÉJÀ ANALYSÉS ({len(buy_list)}) : "
        + (json.dumps(buy_list, ensure_ascii=False)[:3500] if buy_list else
           "aucun encore - c'est ATTENDU à ce stade : l'analyse des titres du benchmark se "
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
