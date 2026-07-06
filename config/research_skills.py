"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  CONFIG / RESEARCH SKILLS — CATALOGUE DES SKILLS DE RECHERCHE                ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Inspiré du plugin Claude `equity-research`. Chaque skill a :                 ║
║    - une clé courte (id technique)                                            ║
║    - un label affiché côté UI                                                 ║
║    - une description (tooltip)                                                ║
║    - une liste de questions pour le wizard (avec options cliquables)          ║
║    - un prompt système dédié pour Claude                                      ║
║    - un format d'output recommandé                                            ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

from typing import Any, Dict, List

# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║  TYPES DE QUESTIONS DU WIZARD                                                ║
# ║  - "single"   : une option parmi N (radio / chips)                          ║
# ║  - "multi"    : plusieurs options (checkboxes / chips multi)                ║
# ║  - "text"     : zone de texte libre                                          ║
# ║  - "ticker"   : champ ticker avec autocomplete                               ║
# ║  - "number"   : nombre (avec min/max optionnel)                              ║
# ║  - "date"     : date picker                                                  ║
# ╚═════════════════════════════════════════════════════════════════════════════╝


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║  CATALOGUE DES SKILLS                                                        ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

RESEARCH_SKILLS: Dict[str, Dict[str, Any]] = {

    # ─────────────────────────────────────────────────────────────────────────
    # 1. EARNINGS ANALYSIS — Note post-publication
    # ─────────────────────────────────────────────────────────────────────────
    "earnings": {
        "label": "Earnings Analysis",
        "icon": "ER",
        "tagline": "Note post-publication d'un trimestre",
        "description": "Analyse complète après une publication trimestrielle : beat/miss, drivers, guidance, thèse révisée.",
        "questions": [
            {
                "id": "ticker", "type": "ticker",
                "label": "Société à analyser",
                "placeholder": "Ex : AAPL, MSFT, NVDA",
                "required": True,
            },
            {
                "id": "trimestre", "type": "single",
                "label": "Trimestre fiscal",
                "options": ["Q1", "Q2", "Q3", "Q4"],
                "required": True,
            },
            {
                "id": "annee_fiscale", "type": "single",
                "label": "Année fiscale",
                "options": ["FY24", "FY25", "FY26", "FY27"],
                "required": True,
            },
            {
                "id": "biais", "type": "single",
                "label": "Votre biais actuel sur le titre",
                "options": ["Bullish", "Neutral", "Bearish", "Pas d'opinion"],
                "required": False,
            },
            {
                "id": "axes_focus", "type": "multi",
                "label": "Axes à creuser en priorité",
                "options": ["Revenus & croissance", "Marges", "Guidance", "Cash flow",
                            "Bilan", "KPI segment", "Capital allocation", "Macro impact"],
                "required": False,
            },
            {
                "id": "contexte", "type": "text",
                "label": "Contexte additionnel (optionnel)",
                "placeholder": "Ex : sortie d'un produit, changement de CFO, restructuration en cours...",
                "required": False,
            },
        ],
        "system_prompt": (
            "Tu es un Equity Research Senior buy-side. Génère une note post-publication "
            "structurée 3000-5000 mots avec EXACTEMENT ces sections :\n"
            " 1. EXECUTIVE SUMMARY (3-4 lignes punchy : beat/in-line/miss + thèse)\n"
            " 2. BEAT/MISS SUMMARY (tableau Métrique | Reported | Consensus | Surprise %)\n"
            " 3. PERFORMANCE DRIVERS (décomposition revenu : volume, prix, mix, FX + drivers de marge)\n"
            " 4. GUIDANCE (nouveau guide vs ancien guide vs consensus, lecture stratégique)\n"
            " 5. UPDATED ESTIMATES (vos estimés vs consensus pour FY1 et FY2)\n"
            " 6. SEGMENT DEEP-DIVE (1-3 segments clés)\n"
            " 7. KEY KPI EVOLUTION (3-5 KPI métier avec tendance)\n"
            " 8. THESIS UPDATE (qu'est-ce qui change, ce qui ne change pas, conviction level 1-5)\n"
            " 9. RISKS & MONITORS (3 risques principaux, métriques à surveiller)\n"
            "10. RECOMMANDATION (BUY/HOLD/SELL + fair value range + horizon)\n\n"
            "Style : direct, factuel, chiffres précis. Markdown propre avec tableaux. "
            "Pas d'emoji. Si tu n'as pas une donnée, écris 'N/D' plutôt que d'inventer."
        ),
        "output_filename_prefix": "Earnings",
    },

    # ─────────────────────────────────────────────────────────────────────────
    # 2. MORNING NOTE — Note matinale courte
    # ─────────────────────────────────────────────────────────────────────────
    "morning_note": {
        "label": "Morning Note",
        "icon": "MN",
        "tagline": "Note matinale 1-2 pages",
        "description": "Note de réunion matinale : highlights overnight, idées du jour, catalyseurs immédiats.",
        "questions": [
            {
                "id": "tickers", "type": "text",
                "label": "Tickers à couvrir",
                "placeholder": "Ex : AAPL, MSFT, NVDA, ASML (séparés par virgules)",
                "required": True,
            },
            {
                "id": "perimetre", "type": "single",
                "label": "Périmètre",
                "options": ["US", "Europe", "Asia", "Global", "Émergents"],
                "required": True,
            },
            {
                "id": "longueur", "type": "single",
                "label": "Longueur cible",
                "options": ["Courte (1 page)", "Standard (2 pages)", "Détaillée (3 pages)"],
                "required": False,
            },
            {
                "id": "themes", "type": "multi",
                "label": "Thèmes à couvrir",
                "options": ["News overnight", "Mouvements pré-marché", "Earnings du jour",
                            "Recos analystes", "Macro events", "Catalyseurs imminents"],
                "required": False,
            },
        ],
        "system_prompt": (
            "Tu es un sell-side analyst rédigeant une morning note. Format strict :\n"
            " 1. HEADLINES (3-5 titres punchy, 1 ligne chacun)\n"
            " 2. WHAT MOVED OVERNIGHT (mouvements >2% sur les tickers, drivers)\n"
            " 3. EARNINGS DU JOUR (publications attendues + consensus)\n"
            " 4. RECOS ANALYSTES (upgrades/downgrades pertinents)\n"
            " 5. MACRO BACKDROP (1 paragraphe, contexte du jour)\n"
            " 6. IDÉES À SUIVRE (2-3 noms avec angle court)\n"
            " 7. CATALYSEURS À VENIR (calendrier 5-10 jours)\n\n"
            "Style : très concis, télégraphique, chiffres précis. Markdown simple."
        ),
        "output_filename_prefix": "MorningNote",
    },

    # ─────────────────────────────────────────────────────────────────────────
    # 3. SCREEN — Génération d'idées
    # ─────────────────────────────────────────────────────────────────────────
    "screen": {
        "label": "Idea Screen",
        "icon": "ID",
        "tagline": "Génération d'idées d'investissement",
        "description": "Screen quantitatif ou thématique. Sortie : 5-15 idées avec thèse courte chacune.",
        "questions": [
            {
                "id": "long_short", "type": "single",
                "label": "Type de positions",
                "options": ["Long only", "Short only", "Long/short pair"],
                "required": True,
            },
            {
                "id": "univers", "type": "single",
                "label": "Univers d'investissement",
                "options": ["Tech", "Santé", "Finance", "Énergie", "Industrie",
                            "Consommation", "Matériaux", "Immobilier", "Multi-secteur"],
                "required": True,
            },
            {
                "id": "style", "type": "single",
                "label": "Style d'investissement",
                "options": ["Value", "GARP", "Growth", "Quality", "Momentum", "Dislocation/Special situation"],
                "required": True,
            },
            {
                "id": "taille_capi", "type": "single",
                "label": "Taille de capitalisation",
                "options": ["Mega (>$200B)", "Large ($10-200B)", "Mid ($2-10B)",
                            "Small ($300M-2B)", "Micro (<$300M)", "Tous"],
                "required": True,
            },
            {
                "id": "geo", "type": "single",
                "label": "Zone géographique",
                "options": ["US", "Europe", "Asia ex-China", "China/HK", "Global DM", "Émergents"],
                "required": True,
            },
            {
                "id": "nb_idees", "type": "single",
                "label": "Nombre d'idées en sortie",
                "options": ["3", "5", "8", "10", "15"],
                "required": True,
            },
            {
                "id": "themes_macro", "type": "multi",
                "label": "Thèmes macro à intégrer (optionnel)",
                "options": ["IA", "Transition énergétique", "Réindustrialisation", "Démographie",
                            "Géopolitique", "Régulation", "Cycle taux", "Cycle dollar"],
                "required": False,
            },
            {
                "id": "contraintes", "type": "text",
                "label": "Contraintes additionnelles",
                "placeholder": "Ex : exclure défense, ESG-friendly, dividende > 2%",
                "required": False,
            },
        ],
        "system_prompt": (
            "Tu es un PM senior. Génère un screen d'idées d'investissement structuré :\n"
            " 1. EXECUTIVE SUMMARY (logique du screen, contexte, 4-5 lignes)\n"
            " 2. UNIVERS & FILTRES (résumé des critères appliqués)\n"
            " 3. IDÉES (pour chacune : ticker, nom, secteur, prix actuel, market cap, "
            "    thèse 3-5 lignes, 3 catalyseurs, prix cible, upside %, conviction 1-5)\n"
            " 4. RANKING (tableau récap classé par conviction décroissante)\n"
            " 5. SCREENS À EXCLURE (1-2 noms qui semblent attractifs mais à éviter, et pourquoi)\n"
            " 6. NEXT STEPS (3 idées à creuser en deep-dive)\n\n"
            "Pour chaque idée : sois précis sur le ticker (convention Yahoo Finance). "
            "Pas d'emoji. Markdown propre."
        ),
        "output_filename_prefix": "Screen",
    },

    # ─────────────────────────────────────────────────────────────────────────
    # 4. SECTOR OVERVIEW — Primer sectoriel
    # ─────────────────────────────────────────────────────────────────────────
    "sector": {
        "label": "Sector Overview",
        "icon": "SO",
        "tagline": "Primer sectoriel approfondi",
        "description": "Vue d'ensemble d'un secteur : TAM, dynamiques compétitives, leaders, risques.",
        "questions": [
            {
                "id": "secteur", "type": "single",
                "label": "Secteur",
                "options": ["Semi-conducteurs", "Software/SaaS", "AI/Cloud infra", "Cybersécurité",
                            "Internet/Plateformes", "Hardware", "Pharma", "Biotech", "Medtech",
                            "Banques", "Assurance", "Asset Management", "Energie traditionnelle",
                            "Énergies renouvelables", "Utilities", "Aérospatial/Défense",
                            "Industrie lourde", "Auto/Mobilité", "Conso staples", "Conso discretionary",
                            "Luxe", "Distribution", "Immobilier", "REITs", "Matériaux"],
                "required": True,
            },
            {
                "id": "geo", "type": "single",
                "label": "Zone géographique",
                "options": ["US", "Europe", "Asia ex-China", "China/HK", "Global DM", "Émergents"],
                "required": True,
            },
            {
                "id": "horizon", "type": "single",
                "label": "Horizon de l'analyse",
                "options": ["12 mois", "3 ans", "5 ans", "10 ans"],
                "required": True,
            },
            {
                "id": "angles", "type": "multi",
                "label": "Angles à creuser",
                "options": ["TAM & croissance", "Structure compétitive", "Innovation & R&D",
                            "Régulation", "Dynamique des marges", "Cycles", "M&A activity",
                            "Disruption technologique", "ESG/durabilité", "Géopolitique"],
                "required": False,
            },
        ],
        "system_prompt": (
            "Tu es un sell-side analyst senior couvrant ce secteur. Génère un primer sectoriel :\n"
            " 1. EXECUTIVE SUMMARY (5-7 lignes : où en est le secteur, dynamique, vue forward)\n"
            " 2. TAM & CROISSANCE (taille de marché, CAGR, segmentations)\n"
            " 3. STRUCTURE COMPÉTITIVE (concentration, leaders, challengers, entrants)\n"
            " 4. KEY DRIVERS (5-8 leviers de croissance/marge structurels)\n"
            " 5. KEY RISKS (5-8 risques structurels et conjoncturels)\n"
            " 6. LEADERS À COUVRIR (5-10 noms avec ticker, market cap, point fort)\n"
            " 7. KPI SECTORIELS À SUIVRE (3-5 métriques clés)\n"
            " 8. VALUATION FRAMEWORK (multiples typiques, ranges historiques)\n"
            " 9. THÈSE FORWARD (3 scénarios : bull / base / bear, probabilités)\n"
            "10. CATALYSEURS 12 MOIS (5-8 events à surveiller)\n\n"
            "Sois précis, sourcé. Pas d'emoji."
        ),
        "output_filename_prefix": "Sector",
    },

    # ─────────────────────────────────────────────────────────────────────────
    # 5. THESIS TRACKER — Création/MAJ d'une thèse
    # ─────────────────────────────────────────────────────────────────────────
    "thesis": {
        "label": "Thesis Tracker",
        "icon": "TH",
        "tagline": "Création / mise à jour d'une thèse d'investissement",
        "description": "Construit une thèse structurée : variant view, catalyseurs, fair value, monitoring KPI.",
        "questions": [
            {
                "id": "ticker", "type": "ticker",
                "label": "Ticker",
                "placeholder": "Ex : NVDA",
                "required": True,
            },
            {
                "id": "side", "type": "single",
                "label": "Direction de la thèse",
                "options": ["Long", "Short", "Pair (long/short)"],
                "required": True,
            },
            {
                "id": "horizon", "type": "single",
                "label": "Horizon",
                "options": ["6 mois", "12 mois", "2 ans", "3-5 ans"],
                "required": True,
            },
            {
                "id": "conviction_initiale", "type": "single",
                "label": "Conviction initiale (1-5)",
                "options": ["1 - faible", "2", "3 - médiane", "4", "5 - forte"],
                "required": True,
            },
            {
                "id": "variant_view", "type": "text",
                "label": "Votre variant view (en quoi vous différez du marché)",
                "placeholder": "Ex : le marché sous-estime la marge SaaS de Snowflake post-AI...",
                "required": True,
            },
        ],
        "system_prompt": (
            "Tu es un PM senior. Construis une thèse d'investissement institutionnelle :\n"
            " 1. ONE-LINER (1 phrase qui résume la thèse)\n"
            " 2. EXECUTIVE SUMMARY (5-7 lignes : pourquoi maintenant, quel call)\n"
            " 3. VARIANT VIEW vs CONSENSUS (où l'on diffère, pourquoi)\n"
            " 4. KEY DRIVERS (3-5 piliers économiques de la thèse)\n"
            " 5. CATALYSEURS (5-8 events qui débloquent la valeur)\n"
            " 6. FAIR VALUE (méthodologie, range, point estimate, upside %)\n"
            " 7. RISK FACTORS (5 risques majeurs avec impact estimé)\n"
            " 8. MONITORING KPI (5-8 indicateurs à surveiller pour invalider/confirmer)\n"
            " 9. SCENARIOS (bull/base/bear : prix cible, probabilité, déclencheurs)\n"
            "10. SIZING & EXIT RULES (poids cible, stop, profit target, durée max)\n\n"
            "Style institutionnel, sans emoji."
        ),
        "output_filename_prefix": "Thesis",
    },

    # ─────────────────────────────────────────────────────────────────────────
    # 6. CATALYST CALENDAR — Calendrier des catalyseurs
    # ─────────────────────────────────────────────────────────────────────────
    "catalysts": {
        "label": "Catalyst Calendar",
        "icon": "CA",
        "tagline": "Calendrier des catalyseurs à venir",
        "description": "Liste des events à venir sur un univers : earnings, FDA, conférences, M&A potentiels.",
        "questions": [
            {
                "id": "tickers", "type": "text",
                "label": "Tickers couverts",
                "placeholder": "Ex : NVDA, MSFT, AAPL (séparés par virgules)",
                "required": True,
            },
            {
                "id": "horizon", "type": "single",
                "label": "Horizon",
                "options": ["Cette semaine", "Ce mois", "3 mois", "6 mois", "12 mois"],
                "required": True,
            },
            {
                "id": "types_events", "type": "multi",
                "label": "Types d'events à inclure",
                "options": ["Earnings", "Guidance updates", "Investor days",
                            "Conférences sectorielles", "FDA / régulateurs",
                            "Lancements produits", "M&A", "IPO/Spin-offs",
                            "Macro releases", "Élections / politique"],
                "required": False,
            },
        ],
        "system_prompt": (
            "Tu es un PM. Construis un calendrier des catalyseurs structuré :\n"
            "Format tableau : Date | Ticker | Type | Description | Niveau d'impact (faible/moyen/élevé) | "
            "Direction probable (positive/négative/neutre)\n\n"
            "Ordonne par date croissante. Ajoute en début un EXECUTIVE SUMMARY de 5 lignes "
            "qui identifie les 3-5 events les plus impactants.\n\n"
            "Pour chaque event majeur : courte note explicative (2-3 phrases).\n"
            "Si une date n'est pas certaine, écris 'TBD - estimé X' plutôt que d'inventer."
        ),
        "output_filename_prefix": "Catalysts",
    },

    # ─────────────────────────────────────────────────────────────────────────
    # 7. INITIATING COVERAGE — Rapport d'initiation (version simplifiée 10p)
    # ─────────────────────────────────────────────────────────────────────────
    "initiation": {
        "label": "Initiating Coverage",
        "icon": "IC",
        "tagline": "Rapport d'initiation institutionnel",
        "description": "Rapport long format pour démarrer une couverture : business overview, modèle, valorisation, recommandation.",
        "questions": [
            {
                "id": "ticker", "type": "ticker",
                "label": "Ticker à couvrir",
                "required": True,
            },
            {
                "id": "recommandation_visee", "type": "single",
                "label": "Recommandation visée",
                "options": ["BUY", "HOLD", "SELL", "Pas encore décidé"],
                "required": False,
            },
            {
                "id": "fair_value_method", "type": "single",
                "label": "Méthode de fair value",
                "options": ["DCF", "Comparables (multiples)", "Sum-of-the-parts", "DCF + comps", "DCF + comps + SOTP"],
                "required": True,
            },
            {
                "id": "horizon", "type": "single",
                "label": "Horizon de la fair value",
                "options": ["12 mois", "18 mois", "24 mois"],
                "required": True,
            },
            {
                "id": "angles", "type": "multi",
                "label": "Angles à approfondir",
                "options": ["Business model", "Moat / avantages compétitifs", "Management quality",
                            "Capital allocation", "Croissance organique vs M&A",
                            "Marges / opérationnel", "Bilan / cash flow", "Catalyseurs",
                            "ESG / régulation", "Disruption risque"],
                "required": False,
            },
        ],
        "system_prompt": (
            "Tu es un sell-side senior analyst. Rédige un rapport d'initiation INSTITUTIONNEL "
            "version condensée (10 pages, ~5000-7000 mots), avec ces sections :\n"
            " 1. EXECUTIVE SUMMARY (10 lignes punchy + recommandation + fair value range)\n"
            " 2. INVESTMENT THESIS (3-5 piliers de la thèse)\n"
            " 3. COMPANY OVERVIEW (business model, segments, géographies)\n"
            " 4. INDUSTRY POSITIONING (place dans l'écosystème, parts de marché, moat)\n"
            " 5. FINANCIAL OUTLOOK (projections 3-5 ans : revenus, marges, FCF, key KPI)\n"
            " 6. VALUATION (DCF/comps/SOTP avec hypothèses explicites, fair value range)\n"
            " 7. CATALYSEURS (5-8 events à 12-24 mois)\n"
            " 8. KEY RISKS (5 risques avec mitigants)\n"
            " 9. ESG & GOUVERNANCE (4-5 lignes)\n"
            "10. RECOMMANDATION (BUY/HOLD/SELL + cible + horizon + sizing suggéré)\n\n"
            "Pour les hypothèses de modèle : sois explicite sur le WACC, growth terminal, "
            "marge cible, multiple de sortie. Tableaux markdown lisibles. Pas d'emoji."
        ),
        "output_filename_prefix": "Initiation",
    },
}


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║  HELPERS                                                                     ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

def list_skills() -> List[Dict[str, str]]:
    """Liste légère des skills (pour le menu côté UI)."""
    return [
        {
            "id":          k,
            "label":       v["label"],
            "icon":        v["icon"],
            "tagline":     v["tagline"],
            "description": v["description"],
        }
        for k, v in RESEARCH_SKILLS.items()
    ]


def get_skill(skill_id: str) -> Dict[str, Any]:
    """Retourne un skill complet (avec questions et prompt)."""
    if skill_id not in RESEARCH_SKILLS:
        return {}
    return RESEARCH_SKILLS[skill_id]


def get_questions(skill_id: str) -> List[Dict[str, Any]]:
    """Retourne uniquement les questions d'un skill (pour le wizard)."""
    skill = get_skill(skill_id)
    return skill.get("questions", [])
