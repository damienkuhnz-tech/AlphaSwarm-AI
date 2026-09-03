"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  TOOLS / SECTOR BETA - SEGMENTATION QUANTITATIVE GICS PAR PROFIL DE RISQUE ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Rôle : fournir une classification empirique des 11 secteurs GICS           ║
║         basée sur leurs betas historiques, et mapper chaque profil de       ║
║         risque aux secteurs compatibles avec sa fourchette de beta cible.   ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Principe :                                                                 ║
║    1. GICS_SECTOR_BETA  → beta min/max/médian empirique par secteur         ║
║    2. RISK_PROFILE_BETA → fourchette de beta cible par profil               ║
║    3. get_sector_classification() → PRIMARY / SECONDARY / EXCLUDED          ║
║    4. build_sector_weights()      → poids max par secteur pour le mandat    ║
║                                                                              ║
║  Diversification forcée :                                                   ║
║    - Min secteurs imposé par profil (4 conservateur → 3 agressif)           ║
║    - Plafond sur secteur unique (30% conservateur → 40% agressif)           ║
║    - Total secteurs secondaires plafonné (20% conservateur → 35% agressif)  ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

from typing import Dict, List, Tuple


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║  TABLE 1 - BETAS EMPIRIQUES PAR SECTEUR GICS                               ║
# ║  Source : moyennes historiques sur marchés développés (MSCI World base).   ║
# ║  Beta mesuré vs MSCI World, rolling 5 ans, médiane sur 2015-2025.          ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

GICS_SECTOR_BETA: Dict[str, dict] = {

    "Utilities": {
        "beta_min": 0.30,
        "beta_max": 0.60,
        "beta_med": 0.45,
        "type": "defensif",
        "description": "Très défensif - revenus réglementés, dividendes stables, peu sensible au cycle",
        "exemples_tickers": ["NEE", "DUK", "ENEL.MI", "IBE.MC", "RWE.DE"],
    },

    "Consommation_courante": {
        "beta_min": 0.40,
        "beta_max": 0.70,
        "beta_med": 0.55,
        "type": "defensif",
        "description": "Défensif - demande non cyclique, pricing power fort, FCF très stable",
        "exemples_tickers": ["NESN.SW", "PG", "KO", "UL", "WMT"],
    },

    "Sante": {
        "beta_min": 0.50,
        "beta_max": 0.85,
        "beta_med": 0.68,
        "type": "defensif",
        "description": "Défensif - innovation structurelle, barrières réglementaires, récurrent",
        "exemples_tickers": ["JNJ", "NVO", "ROG.SW", "AZN.L", "LLY"],
    },

    "Immobilier": {
        "beta_min": 0.60,
        "beta_max": 1.00,
        "beta_med": 0.80,
        "type": "intermediaire",
        "description": "Semi-défensif - sensible aux taux d'intérêt, revenus locatifs prévisibles",
        "exemples_tickers": ["SPG", "PLD", "UNIBAIL.PA", "PSA", "DLR"],
    },

    "Communication": {
        "beta_min": 0.60,
        "beta_max": 1.10,
        "beta_med": 0.85,
        "type": "intermediaire",
        "description": "Mixte - télécoms défensifs (β<0.8) vs media/tech offensifs (β>1.0)",
        "exemples_tickers": ["DTE.DE", "VOD.L", "GOOGL", "META", "T"],
    },

    "Finance": {
        "beta_min": 0.80,
        "beta_max": 1.20,
        "beta_med": 1.00,
        "type": "intermediaire",
        "description": "Intermédiaire - cyclique modéré, sensible aux taux, levier bancaire",
        "exemples_tickers": ["JPM", "BNP.PA", "HSBA.L", "V", "AXA.PA"],
    },

    "Industrie": {
        "beta_min": 0.85,
        "beta_max": 1.20,
        "beta_med": 1.02,
        "type": "intermediaire",
        "description": "Intermédiaire - cyclique mais leaders mondiaux avec visibilité long terme",
        "exemples_tickers": ["SIE.DE", "HON", "CAT", "GE", "ABB.SW"],
    },

    "Materiaux": {
        "beta_min": 0.85,
        "beta_max": 1.25,
        "beta_med": 1.05,
        "type": "cyclique",
        "description": "Cyclique - lié aux matières premières et au cycle industriel mondial",
        "exemples_tickers": ["LIN", "APD", "BHP", "RIO", "NEM"],
    },

    "Energie": {
        "beta_min": 0.85,
        "beta_max": 1.35,
        "beta_med": 1.10,
        "type": "cyclique",
        "description": "Cyclique - corrélé au prix du pétrole/gaz, risque géopolitique élevé",
        "exemples_tickers": ["XOM", "TTE.PA", "SHEL.L", "CVX", "BP.L"],
    },

    "Consommation_discretionnaire": {
        "beta_min": 1.00,
        "beta_max": 1.45,
        "beta_med": 1.22,
        "type": "offensif",
        "description": "Offensif - très cyclique, dépend du cycle consommateur et de la confiance",
        "exemples_tickers": ["AMZN", "TSLA", "MC.PA", "NKE", "HD"],
    },

    "Technologie": {
        "beta_min": 1.10,
        "beta_max": 1.80,
        "beta_med": 1.45,
        "type": "offensif",
        "description": "Très offensif - forte croissance, valorisations élevées, haute volatilité",
        "exemples_tickers": ["NVDA", "AAPL", "MSFT", "ASML.AS", "TSM"],
    },
}


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║  TABLE 2 - FOURCHETTES DE BETA CIBLE PAR PROFIL DE RISQUE                  ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

RISK_PROFILE_BETA: Dict[str, dict] = {

    "conservateur": {
        "beta_min": 0.40,
        "beta_max": 0.85,
        "beta_cible_portefeuille": "0.50 - 0.75",
        "overlap_tolerance": 0.10,     # Secteurs secondaires : jusqu'à 0.10 hors fourchette
        "min_secteurs": 4,             # Diversification minimale imposée
        "max_pct_secteur_primaire": 30, # Max 30% dans un seul secteur primaire
        "max_pct_secteur_secondaire": 12,
        "max_pct_total_secondaire": 20, # Max 20% total en secteurs secondaires
        "description": "Préservation du capital - secteurs défensifs, dividendes, bilan solide",
    },

    "modere": {
        "beta_min": 0.65,
        "beta_max": 1.05,
        "beta_cible_portefeuille": "0.75 - 0.95",
        "overlap_tolerance": 0.12,
        "min_secteurs": 5,
        "max_pct_secteur_primaire": 25,
        "max_pct_secteur_secondaire": 15,
        "max_pct_total_secondaire": 25,
        "description": "Équilibre rendement/risque - mix défensif/intermédiaire",
    },

    "equilibre": {
        "beta_min": 0.85,
        "beta_max": 1.20,
        "beta_cible_portefeuille": "0.95 - 1.10",
        "overlap_tolerance": 0.15,
        "min_secteurs": 6,
        "max_pct_secteur_primaire": 22,
        "max_pct_secteur_secondaire": 18,
        "max_pct_total_secondaire": 35,
        "description": "Croissance diversifiée - tous secteurs intermédiaires, beta proche 1",
    },

    "dynamique": {
        "beta_min": 1.05,
        "beta_max": 1.40,
        "beta_cible_portefeuille": "1.10 - 1.30",
        "overlap_tolerance": 0.12,
        "min_secteurs": 4,
        "max_pct_secteur_primaire": 35,
        "max_pct_secteur_secondaire": 20,
        "max_pct_total_secondaire": 30,
        "description": "Performance prioritaire - secteurs offensifs/cycliques dominants",
    },

    "agressif": {
        "beta_min": 1.25,
        "beta_max": 1.70,
        "beta_cible_portefeuille": "1.30 - 1.55",
        "overlap_tolerance": 0.10,
        "min_secteurs": 3,
        "max_pct_secteur_primaire": 40,
        "max_pct_secteur_secondaire": 25,
        "max_pct_total_secondaire": 35,
        "description": "Rendement maximal - concentration sur secteurs à fort beta",
    },
}


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║  FONCTION 1 - CLASSIFICATION PRIMARY / SECONDARY / EXCLUDED               ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

def get_sector_classification(profil_risque: str) -> dict:
    """
    Classifie les 11 secteurs GICS selon leur compatibilité beta avec le profil.

    Logique de classification :
      PRIMARY   : beta_med du secteur est DANS la fourchette [beta_min, beta_max] du profil
      SECONDARY : chevauchement partiel après application de la tolérance
      EXCLUDED  : aucun chevauchement même avec tolérance

    Returns:
        dict avec clés "primary", "secondary", "excluded", "profile"
    """
    profile = RISK_PROFILE_BETA.get(profil_risque, RISK_PROFILE_BETA["equilibre"])
    p_min = profile["beta_min"]
    p_max = profile["beta_max"]
    tol   = profile["overlap_tolerance"]

    primary   = {}
    secondary = {}
    excluded  = {}

    for sector, data in GICS_SECTOR_BETA.items():
        s_min = data["beta_min"]
        s_max = data["beta_max"]
        s_med = data["beta_med"]

        if p_min <= s_med <= p_max:
            # Le beta médian du secteur tombe dans la fourchette cible → PRIMARY
            primary[sector] = data

        elif (s_max >= p_min - tol) and (s_min <= p_max + tol):
            # Chevauchement partiel avec tolérance → SECONDARY
            secondary[sector] = data

        else:
            # Aucun chevauchement → EXCLUDED
            excluded[sector] = data

    return {
        "primary":   primary,
        "secondary": secondary,
        "excluded":  excluded,
        "profile":   profile,
    }


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║  FONCTION 2 - POIDS MAX PAR SECTEUR POUR LE TEMPLATE MANDAT               ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

def build_sector_weights(profil_risque: str) -> Dict[str, dict]:
    """
    Calcule les poids min/max par secteur à injecter dans le template du MandateAgent.

    Règles de diversification :
      - Secteurs primaires : poids distribué équitablement, plafonné à max_pct_secteur_primaire
        → 70% alloués aux primaires, divisé par le nombre de secteurs primaires
      - Secteurs secondaires : plafonné à max_pct_secteur_secondaire
      - Secteurs exclus : max = 0%
      - Min secteurs : respecté en forçant un min > 0 sur les N premiers primaires

    Returns:
        Dict {secteur: {"max": float, "min": float}}
    """
    classif = get_sector_classification(profil_risque)
    profile = classif["profile"]

    primary   = classif["primary"]
    secondary = classif["secondary"]
    excluded  = classif["excluded"]

    n_primary = len(primary)
    min_sect  = profile["min_secteurs"]

    # ── Calcul du poids max pour secteurs primaires ───────────────────────────
    # On distribue 75% du portefeuille entre les primaires (le reste va aux secondaires).
    # Plafonné par max_pct_secteur_primaire (ex: 30% pour conservateur).
    if n_primary > 0:
        base_primary_max = min(
            round(75 / n_primary / 100, 2),              # Distribution équitable
            profile["max_pct_secteur_primaire"] / 100,   # Plafond par secteur
        )
    else:
        base_primary_max = 0.25  # Fallback

    # ── Calcul du poids min pour les N premiers primaires (diversification) ──
    # On force un min > 0 sur les secteurs primaires pour garantir la diversification.
    # Les secteurs primaires au-delà du min_secteurs requis ont min = 0.
    primary_sectors_sorted = sorted(
        primary.keys(),
        key=lambda s: primary[s]["beta_med"]  # Tri par beta médian croissant
    )

    result = {}

    for i, sector in enumerate(primary_sectors_sorted):
        min_weight = 0.02 if i < min_sect else 0.00
        result[sector] = {
            "max": base_primary_max,
            "min": min_weight,
        }

    # ── Poids pour secteurs secondaires ──────────────────────────────────────
    secondary_max = profile["max_pct_secteur_secondaire"] / 100
    for sector in secondary:
        result[sector] = {
            "max": secondary_max,
            "min": 0.00,
        }

    # ── Poids nuls pour secteurs exclus ──────────────────────────────────────
    for sector in excluded:
        result[sector] = {
            "max": 0.00,
            "min": 0.00,
        }

    return result


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║  FONCTION 3 - TEXTE FORMATÉ POUR L'INJECTION DANS LES PROMPTS LLM         ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

def format_sector_directive_for_prompt(profil_risque: str) -> str:
    """
    Génère un bloc texte structuré décrivant la classification sectorielle
    pour injection directe dans les prompts des agents LLM.

    Format :
      SECTEURS PRIMAIRES (beta compatible) :
        • Utilities          β 0.30-0.60 [médian 0.45] → max 30% - Très défensif
        ...
      SECTEURS SECONDAIRES (overlap partiel) :
        • Communication      β 0.60-1.10 [médian 0.85] → max 12% - Mixte
        ...
      SECTEURS EXCLUS (beta incompatible) :
        • Technologie        β 1.10-1.80 [médian 1.45] → 0%     - Très offensif
        ...
    """
    classif = get_sector_classification(profil_risque)
    weights = build_sector_weights(profil_risque)
    profile = classif["profile"]

    lines = [
        f"SEGMENTATION SECTORIELLE QUANTITATIVE - PROFIL {profil_risque.upper()}",
        f"Beta portefeuille cible : {profile['beta_cible_portefeuille']}",
        f"Diversification minimale : {profile['min_secteurs']} secteurs distincts obligatoires",
        f"Total secteurs secondaires : max {profile['max_pct_total_secondaire']}% du portefeuille",
        "",
        "SECTEURS PRIMAIRES - beta compatible, surpondération autorisée :",
    ]
    for s, data in classif["primary"].items():
        w = weights[s]
        lines.append(
            f"  • {s:<32} β méd {data['beta_med']:.2f}  →  max {w['max']*100:.0f}%"
        )

    lines.append("")
    lines.append("SECTEURS SECONDAIRES - overlap partiel, poids limité :")
    for s, data in classif["secondary"].items():
        w = weights[s]
        lines.append(
            f"  • {s:<32} β méd {data['beta_med']:.2f}  →  max {w['max']*100:.0f}%"
        )

    lines.append("")
    lines.append("SECTEURS EXCLUS - poids = 0% :")
    for s in classif["excluded"]:
        lines.append(f"  • {s}")

    return "\n".join(lines)


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║  FONCTION 4 - NORMALISATION DES NOMS DE SECTEURS                          ║
# ║  Le LLM retourne parfois "Technology", "tech", "Santé", "Healthcare"...   ║
# ║  Cette fonction ramène tout aux 11 clés canoniques de GICS_SECTOR_BETA.   ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

# Table de correspondance : variantes LLM → nom canonique GICS
_SECTOR_ALIASES: Dict[str, str] = {
    # Technologie
    "technologie":                   "Technologie",
    "technology":                    "Technologie",
    "tech":                          "Technologie",
    "information technology":        "Technologie",
    "it":                            "Technologie",
    "semiconducteurs":               "Technologie",
    "semiconductors":                "Technologie",
    "logiciels":                     "Technologie",
    "software":                      "Technologie",

    # Santé
    "sante":                         "Sante",
    "santé":                         "Sante",
    "healthcare":                    "Sante",
    "health care":                   "Sante",
    "health":                        "Sante",
    "pharma":                        "Sante",
    "pharmaceutique":                "Sante",
    "pharmaceuticals":               "Sante",
    "biotech":                       "Sante",
    "biotechnology":                 "Sante",

    # Finance
    "finance":                       "Finance",
    "financials":                    "Finance",
    "financial":                     "Finance",
    "banque":                        "Finance",
    "banking":                       "Finance",
    "assurance":                     "Finance",
    "insurance":                     "Finance",

    # Industrie
    "industrie":                     "Industrie",
    "industrials":                   "Industrie",
    "industrial":                    "Industrie",
    "industriel":                    "Industrie",

    # Consommation courante
    "consommation_courante":         "Consommation_courante",
    "consommation courante":         "Consommation_courante",
    "consumer staples":              "Consommation_courante",
    "staples":                       "Consommation_courante",
    "alimentation":                  "Consommation_courante",
    "food":                          "Consommation_courante",
    "biens de consommation":         "Consommation_courante",
    "consumer defensive":            "Consommation_courante",

    # Consommation discrétionnaire
    "consommation_discretionnaire":  "Consommation_discretionnaire",
    "consommation discretionnaire":  "Consommation_discretionnaire",
    "consommation discrétionnaire":  "Consommation_discretionnaire",
    "consumer discretionary":        "Consommation_discretionnaire",
    "discretionary":                 "Consommation_discretionnaire",
    "luxe":                          "Consommation_discretionnaire",
    "luxury":                        "Consommation_discretionnaire",
    "retail":                        "Consommation_discretionnaire",
    "auto":                          "Consommation_discretionnaire",
    "automobile":                    "Consommation_discretionnaire",

    # Communication
    "communication":                 "Communication",
    "communication services":        "Communication",
    "telecom":                       "Communication",
    "télécommunications":            "Communication",
    "telecommunications":            "Communication",
    "media":                         "Communication",
    "médias":                        "Communication",

    # Energie
    "energie":                       "Energie",
    "énergie":                       "Energie",
    "energy":                        "Energie",
    "oil":                           "Energie",
    "gas":                           "Energie",
    "petrole":                       "Energie",
    "pétrole":                       "Energie",

    # Services publics
    "services_publics":              "Utilities",
    "services publics":              "Utilities",
    "utilities":                     "Utilities",
    "utility":                       "Utilities",
    "electricite":                   "Utilities",
    "électricité":                   "Utilities",

    # Matériaux
    "materiaux":                     "Materiaux",
    "matériaux":                     "Materiaux",
    "materials":                     "Materiaux",
    "mining":                        "Materiaux",
    "minier":                        "Materiaux",
    "chimie":                        "Materiaux",
    "chemicals":                     "Materiaux",

    # Immobilier
    "immobilier":                    "Immobilier",
    "real estate":                   "Immobilier",
    "reits":                         "Immobilier",
    "reit":                          "Immobilier",
}


def normalize_sector(secteur_raw: str) -> str:
    """
    Normalise un nom de secteur retourné par le LLM vers le nom canonique GICS.
    Retourne le nom canonique si trouvé, sinon retourne la valeur originale.

    Ex: "Technology" → "Technologie"
        "consumer staples" → "Consommation_courante"
        "Santé" → "Sante"
    """
    if not secteur_raw:
        return secteur_raw

    key = secteur_raw.strip().lower()

    # Correspondance directe dans la table d'alias
    if key in _SECTOR_ALIASES:
        return _SECTOR_ALIASES[key]

    # Si déjà un nom canonique (ex: "Technologie"), retourner tel quel
    if secteur_raw in GICS_SECTOR_BETA:
        return secteur_raw

    # Recherche partielle : si un alias est contenu dans la chaîne
    for alias, canonical in _SECTOR_ALIASES.items():
        if alias in key:
            return canonical

    # Pas trouvé → retourne l'original (ne plante pas)
    return secteur_raw


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║  FONCTION 5 - FILTRE DUR POST-LLM                                          ║
# ║  Élimine toute idée dont le secteur est EXCLU pour le profil donné.        ║
# ║  C'est un filtre DÉTERMINISTE Python - indépendant du LLM.                 ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

def filter_ideas_by_profile(ideas: List, profil_risque: str) -> tuple:
    """
    Filtre une liste d'IdeaOutput en éliminant les idées dont le secteur
    est EXCLU pour le profil de risque donné.

    Args:
        ideas        : liste d'IdeaOutput (ou dicts avec champ "secteur")
        profil_risque: profil de risque ("conservateur", "modere", etc.)

    Returns:
        (ideas_valides, ideas_filtrees)
        ideas_filtrees = liste de dicts {ticker, secteur, raison_rejet}
    """
    classif          = get_sector_classification(profil_risque)
    excluded_sectors = set(classif["excluded"].keys())
    profile          = classif["profile"]

    valides   = []
    filtrees  = []

    for idea in ideas:
        # Gère à la fois les objets Pydantic et les dicts
        secteur_raw = getattr(idea, "secteur", None) or (
            idea.get("secteur", "") if isinstance(idea, dict) else ""
        )
        ticker = getattr(idea, "ticker", None) or (
            idea.get("ticker", "?") if isinstance(idea, dict) else "?"
        )

        secteur_norm = normalize_sector(secteur_raw)

        # Mise à jour du secteur normalisé sur l'objet Pydantic
        if hasattr(idea, "secteur") and secteur_norm != secteur_raw:
            try:
                object.__setattr__(idea, "secteur", secteur_norm)
            except Exception:
                pass

        if secteur_norm in excluded_sectors:
            filtrees.append({
                "ticker":        ticker,
                "secteur_brut":  secteur_raw,
                "secteur_norm":  secteur_norm,
                "raison_rejet":  (
                    f"Secteur '{secteur_norm}' exclu pour profil {profil_risque.upper()} "
                    f"(beta médian {GICS_SECTOR_BETA.get(secteur_norm, {}).get('beta_med', '?')} "
                    f"incompatible avec beta cible {profile['beta_cible_portefeuille']})"
                ),
            })
        else:
            valides.append(idea)

    return valides, filtrees
