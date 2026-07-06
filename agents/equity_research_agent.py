"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  AGENTS / EQUITY RESEARCH AGENT — ÉTAPE 2/5                                 ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Rôle : analyser chaque idée candidate et produire un rapport complet.     ║
║  Input  : ideas (List[IdeaOutput]), mandate (contraintes)                   ║
║  Output : research (List[ResearchOutput]) + rapports HTML par ticker        ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  C'est l'agent le plus lent du workflow (~8-10 min pour 15 titres).        ║
║  Pour chaque ticker, il enchaîne 7 sous-étapes :                           ║
║    1. Pre-fetch données marché réelles (5 appels yfinance)                  ║
║    2. Formatage des données en texte pour le prompt                         ║
║    3. Appel Claude pour générer les 4 sections narratives + rating          ║
║    4. Parsing du JSON retourné                                               ║
║    5. Construction du ResearchOutput Pydantic (pour le workflow)            ║
║    6. Construction du dict complet pour le rapport HTML                     ║
║    7. Génération + sauvegarde du rapport HTML                               ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Conception clé : données réelles PRÉ-FETCHÉES avant l'appel LLM.          ║
║  Raison : évite le tool use (trop lent ticker par ticker).                  ║
║  On collecte tout d'abord, puis Claude raisonne sur des données complètes. ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  IMPORTS                                                                    │
# └─────────────────────────────────────────────────────────────────────────────┘

import json  # Utilisé pour json.dumps dans les prompts et le parsing de réponses

import os
# os.makedirs

from concurrent.futures import ThreadPoolExecutor, as_completed
from rich.console import Console
# ThreadPoolExecutor : exécute _analyze_ticker() sur plusieurs tickers en parallèle.
# as_completed       : itère sur les futures au fur et à mesure qu'elles se terminent.
# Gain attendu : ~5× plus rapide (5 tickers en parallèle au lieu de 1 à la fois).   : crée le dossier outputs/research/ si absent
# os.path.join  : construit le chemin du fichier HTML de manière portable
# os.path.dirname / os.path.abspath : localise la racine du projet
# os.path.relpath : affiche un chemin relatif dans les logs (plus lisible)

from datetime import date
# date.today().strftime : génère la date courante pour nommer les rapports
# Ex: strftime("%Y%m%d") → "20260322" (nom de fichier)
# Ex: strftime("%Y-%m-%d") → "2026-03-22" (dans le rapport)

from typing import Any, Dict, List, Optional
# Any      : type générique pour les dicts de données marché (valeurs hétérogènes)
# Dict     : type des packages de données et des paramètres
# List     : type de la liste d'analyses retournée
# Optional : non utilisé directement ici (laissé pour cohérence avec les autres agents)

from .base_agent import BaseAgent
# Classe mère : fournit _call_llm_with_retry, _parse_json, client Anthropic
# On N'utilise PAS TOOLS ici (TOOLS = []) : voir conception ci-dessus

from config.prompts import EQUITY_RESEARCH_PROMPT
# Prompt système définissant le rôle d'"analyste equity research institutionnel senior"

from models.state import PortfolioState
# Type du dict partagé entre tous les agents

from models.research import ResearchOutput
# Modèle Pydantic de l'analyse d'un titre.
# Contient : ticker, score_conviction, recommandation, poids_suggere_initial
# Ces champs sont lus par PortfolioConstructionAgent pour construire l'allocation.

# ── Imports des 5 fonctions de données marché ─────────────────────────────────
# Chacune effectue un appel yfinance différent.
# Toutes sont appelées dans _fetch_all_market_data() avant l'appel LLM.
from tools.market_data import (
    get_stock_info,        # Prix, market cap, secteur, volume, beta
    get_financials,        # P/E, EV/EBITDA, marges, ROE, croissance
    get_price_history,     # Performance 1 an, volatilité annualisée
    get_annual_financials, # Revenue, Net Income, EBIT margin sur 4 ans
    get_price_series,      # Série normalisée base 100 vs benchmark (pour graphique HTML)
)

from tools.fmp_data import (
    get_fmp_historical_financials, # Revenus, NI, EPS, marges sur 5 ans (FMP)
    get_fmp_historical_ratios,     # P/E, EV/EBITDA, ROE, PB sur 5 ans (FMP)
    get_fmp_analyst_targets,       # Consensus prix cibles analystes (FMP)
)

from tools.web_search import (
    get_web_research,                # 2 recherches Tavily : news + analystes
    format_web_research_for_prompt,  # Formate le résultat en texte pour le LLM
    get_benchmark_constituents,      # 1 recherche Tavily : top holdings du benchmark
)

from tools.sec_edgar import (
    get_sec_annual_report,    # Extrait Item 1A + Item 7 du dernier 10-K
    format_sec_for_prompt,    # Formate les données SEC pour le prompt
)

from tools.report_generator import generate_company_report, generate_sector_report
# Fonction qui prend un dict de données et génère le HTML du rapport institutionnel.
# Implémentée dans tools/report_generator.py.

import unicodedata
import re


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║  PROMPT NARRATIF — TEMPLATE POUR CHAQUE TICKER                             ║
# ║  Défini ici (pas dans config/prompts.py) car il est spécifique à cet agent ║
# ║  et contient des variables de formatage {ticker}, {market_data_text}, etc. ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

console = Console(force_terminal=True, legacy_windows=False)
# Instance partagée par tous les appels à _analyze_ticker().
# Rich.Console est thread-safe → pas de conflit avec ThreadPoolExecutor.

REPORT_NARRATIVE_PROMPT = """Tu es un analyste en equity research travaillant en asset management.

Ton objectif n'est PAS de résumer tout le document, mais d'extraire UNIQUEMENT les éléments les plus pertinents pour une décision d'investissement.

TITRE : {ticker} — {nom}
SECTEUR : {secteur} | GEOGRAPHIE : {geographie}
DATE DU RAPPORT : {report_date}

THESE INITIALE : {raison}
CATALYSEUR : {catalyseur}

DONNEES MARCHE REELLES (yfinance) :
{market_data_text}

CONTRAINTES MANDAT :
- Poids max     : {poids_max}
- Benchmark     : {benchmark}
- Horizon       : {horizon}
- Profil risque : {profil_risque}

---

REGLE DE COHERENCE PROFIL/TITRE (NON-NEGOCIABLE) :
  Le profil de risque est "{profil_risque}". Applique ces regles pour le score_conviction :

  Si profil = conservateur :
    - Titre defensif (Sante, Conso_courante, Services_publics, telecom, beta < 1.0) → score normal
    - Titre offensif ou speculatif (Tech a fort beta, Biotech, beta > 1.2) → PENALITE -25 pts

  Si profil = modere :
    - Mix autorise, beta cible < 1.10
    - Titres tres speculatifs (beta > 1.4) → penalite -15 pts

  Si profil = equilibre :
    - Tous secteurs autorises, pas de penalite profil

  Si profil = dynamique :
    - Titres offensifs/cycliques (Tech, Conso_discre, Energie, beta > 1.1) → bonus +5 pts
    - Titres ultra-defensifs peu porteurs → penalite -10 pts

  Si profil = agressif :
    - Growth/innovation/cycliques favorises, beta > 1.25 ideal
    - Titres defensifs purs (Nestle, Utilities basiques) → penalite -20 pts

  JUSTIFIE TOUJOURS dans "these_investissement" :
    - Le beta reel du titre (depuis les donnees marche)
    - La coherence ou l'incoherence avec le profil "{profil_risque}"
    - L'impact sur le score_conviction

---

CLAUSE ANTI-HALLUCINATION (OBLIGATOIRE) :
- N'invente jamais de données, chiffres ou faits
- Si une information est incertaine ou absente, indique "N/D"
- Distingue clairement dans tes textes : [FAIT] vs [HYPOTHESE] vs [OPINION]
- Base-toi uniquement sur les données marché fournies ci-dessus

---

INSTRUCTIONS PAR CHAMP :

executive_summary (5 lignes max) :
  → Recommandation + upside en 1 ligne
  → 2-3 raisons clés qui justifient la thèse (logique économique, pas de blabla)
  → Le principal risque qui pourrait invalider la thèse
  → Raisonne comme un portfolio manager qui lit en 30 secondes

income_summary (200-300 mots) :
  → Ne décris PAS les chiffres — interprète-les
  → Qu'est-ce que la trajectoire des marges dit sur le business model ?
  → La croissance du revenue est-elle de qualité (mix, pricing power) ou de volume ?
  → Quel est le signal le plus important pour les 12 prochains mois ?

business_highlights (200-300 mots) :
  → Concentre-toi sur les 2-3 avantages concurrentiels durables (moat)
  → Qu'est-ce qui rend ce business difficile à répliquer ?
  → Quels segments ou catalyseurs vont réellement faire bouger le titre ?
  → Privilégie le futur au passé

company_situation (200-300 mots) :
  → Positionnement dans le cycle sectoriel
  → Dynamique concurrentielle : qui menace la position de l'entreprise et comment ?
  → Qualité du management / allocation du capital (si données disponibles)
  → Qu'est-ce qui doit se réaliser pour que la thèse fonctionne ?

risk_assessment (150-200 mots) :
  → Scénarios baissiers concrets (pas de risques génériques)
  → Ce qui invaliderait définitivement la thèse
  → Risques macro, concurrence, régulation, exécution — par ordre de probabilité
  → Pour chaque risque : impact potentiel sur le titre (fort / modéré / faible)

commentaire_valorisation (100-150 mots) :
  → L'action est-elle sous-évaluée ou surévaluée ? Pourquoi ?
  → Compare les multiples aux peers et à l'historique du titre
  → Quelle hypothèse de croissance est déjà pricée dans le cours actuel ?
  → Y a-t-il un catalyseur de re-rating ?

---

Retourne UNIQUEMENT ce JSON valide (pas de texte avant/apres, pas de markdown) :
{{
  "ticker": "{ticker}",
  "nom": "{nom}",
  "rating": "strongBuy",
  "target_price_low": 0,
  "target_price_high": 0,
  "executive_summary": "5 lignes max : recommandation + upside + 2-3 raisons cles + risque principal",
  "income_summary": "200-300 mots : interpretation business de la trajectoire financiere, pas description des chiffres",
  "business_highlights": "200-300 mots : moat, avantages concurrentiels durables, catalyseurs futurs",
  "company_situation": "200-300 mots : cycle sectoriel, dynamique concurrentielle, conditions de succes de la these",
  "risk_assessment": "150-200 mots : scenarios baissiers concrets ordonnes par probabilite avec impact sur le titre",
  "these_investissement": "1 phrase : beta du titre, coherence avec le profil {profil_risque}, conviction ajustee et pourquoi",
  "score_conviction": 75,
  "recommandation": "BUY",
  "poids_suggere_initial": 0.05,
  "risques_cles": ["risque1 — impact fort/modere/faible", "risque2 — impact", "risque3 — impact"],
  "catalyseurs": ["catalyseur1 avec horizon temporel", "catalyseur2", "catalyseur3"],
  "valorisation": {{
    "methode_principale": "DCF / PE relatif / EV/EBITDA",
    "PER_estime_NTM": "N/D",
    "EV_EBITDA_NTM": "N/D",
    "upside_potentiel": "N/D",
    "commentaire_valorisation": "100-150 mots : sous/sur-valorise, multiples vs peers, hypothese de croissance pricee, catalyseur de re-rating"
  }},
  "sources": ["yfinance — données marché temps réel", "SEC EDGAR — filings 10-K/10-Q", "Analyse basée sur les données fournies"]
}}

Champs rating valides : strongBuy, Buy, Hold, Sell
Champs recommandation valides : BUY, HOLD, SELL"""
# Note : rating et recommandation sont deux champs distincts.
# rating          → affiché dans le rapport HTML (style visuel)
# recommandation  → utilisé par PortfolioConstructionAgent pour filtrer les BUY


# ── Prompt pour les rapports sectoriels ────────────────────────────────────────
SECTOR_REPORT_PROMPT = """Tu es un stratégiste sectoriel senior d'une banque d'investissement de premier rang.
En te basant sur les analyses des entreprises ci-dessous, génère un rapport d'analyse sectorielle institutionnel.

SECTEUR : {sector_name}
DATE DU RAPPORT : {report_date}
BENCHMARK : {benchmark}

ENTREPRISES ANALYSÉES DANS CE SECTEUR :
{companies_summary}

Retourne UNIQUEMENT ce JSON valide (pas de texte avant/après, pas de markdown) :
{{
  "sector_overview": "Vue d'ensemble macro du secteur sur 250-350 mots. Tendances structurelles, dynamiques de marché, position dans le cycle économique.",
  "key_drivers": "Catalyseurs de croissance sectoriels sur 150-200 mots. Facteurs technologiques, réglementaires, démographiques qui soutiennent le secteur.",
  "valuation_analysis": "Analyse de valorisation sectorielle sur 150-200 mots. Multiples actuels vs historiques, comparaison inter-sectorielle, attractivité relative.",
  "top_picks": "Présentation des meilleures convictions sur 100-150 mots. Justification du choix des titres avec le meilleur rapport risque/rendement.",
  "risk_factors": "Risques sectoriels spécifiques sur 100-150 mots. Risques macro, réglementaires, concurrentiels, de cycle.",
  "recommended_allocation": "Surpondérer",
  "sector_pe_median": 18.5
}}

Champs recommended_allocation valides : Surpondérer, Neutre, Sous-pondérer
sector_pe_median : float (P/E médian estimé du secteur basé sur les entreprises analysées)"""


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║  CLASSE EQUITYRESEARCHAGENT                                                 ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

class EquityResearchAgent(BaseAgent):

    AGENT_KEY = "research"
    # ── Prompt système ────────────────────────────────────────────────────────
    SYSTEM_PROMPT = EQUITY_RESEARCH_PROMPT
    # Rôle : "analyste equity research senior" d'une banque d'investissement.
    # Instructions : produire des analyses institutionnelles avec rating et JSON strict.

    # ── Outils ────────────────────────────────────────────────────────────────
    TOOLS = []
    # PAS de tool use : les données sont pre-fetchées avant l'appel LLM.
    # Raison : le tool use est séquentiel (1 appel → attente → suivant).

    # ── Univers par défaut élargi ─────────────────────────────────────────────
    # 40 grandes capitalisations diversifiées (secteurs/géo) utilisées quand aucun
    # ticker n'est fourni. Tronqué selon le nombre de positions cible du mandat,
    # pour que la recherche fournisse assez de BUY au PortfolioConstructionAgent.
    _DEFAULT_UNIVERSE = [
        # ── US méga/grandes capis, multi-secteurs ──
        "NVDA", "MSFT", "AAPL", "GOOGL", "AMZN", "META", "AVGO", "LLY", "V", "JPM",
        "MA", "COST", "UNH", "HD", "PG", "JNJ", "ABBV", "ADBE", "CRM", "NFLX",
        "AMD", "ORCL", "ACN", "MRK", "KO", "PEP", "WMT", "TMO", "ABT", "DHR",
        "MCD", "CSCO", "QCOM", "TXN", "INTU", "AMAT", "NOW", "ISRG", "BKNG", "CAT",
        "GE", "HON", "UNP", "LOW", "BLK", "GS", "MS", "AXP", "SPGI", "PLD",
        # ── Europe ──
        "ASML", "SAP", "NVO", "MC.PA", "OR.PA", "NESN.SW", "SIE.DE", "AZN", "SHEL",
        "ULVR.L", "SU.PA", "AIR.PA", "ALV.DE", "DTE.DE", "SAN.PA", "RMS.PA", "IDXX",
        # ── Asie / Émergents ──
        "TSM", "TM", "005930.KS", "BABA", "RELIANCE.NS", "9988.HK", "0700.HK",
        "6758.T", "7203.T", "TCS.NS", "INFY", "9984.T", "1299.HK", "MELI", "SE",
        "JD",
    ]

    @staticmethod
    def _target_positions(mandate) -> int:
        """Nombre de positions cible (borne haute) depuis le mandat. Défaut 10."""
        raw = getattr(mandate, "nombre_positions_cible", None) if mandate else None
        if raw is None:
            return 10
        # raw peut être "8", "25-35", 12... → on prend le plus grand entier présent.
        import re
        nums = [int(n) for n in re.findall(r"\d+", str(raw))]
        return max(nums) if nums else 10
    # Avec 15 tickers × 5 appels yfinance chacun = 75 appels tool use séquentiels
    # → trop lent. Le pre-fetch groupé est plus rapide et prévisible.

    # ── Dossier de sortie des rapports HTML ────────────────────────────────────
    OUTPUT_DIR = os.path.join(
        os.path.dirname(       # Remonte d'un niveau depuis agents/
            os.path.dirname(   # Remonte d'un niveau depuis equity_research_agent.py
                os.path.abspath(__file__)
                # __file__ = chemin absolu de ce fichier
                # Ex: C:\Users\Kylor\alphaswarm\agents\equity_research_agent.py
            )
        ),
        "outputs",    # → C:\Users\Kylor\alphaswarm\outputs
        "research",   # → C:\Users\Kylor\alphaswarm\outputs\research
    )
    # Cette approche est robuste : fonctionne peu importe d'où on lance Python.


    # ┌─────────────────────────────────────────────────────────────────────────┐
    # │  run() — MÉTHODE PRINCIPALE                                             │
    # │  Boucle sur chaque idée et enchaîne les 7 sous-étapes.                │
    # └─────────────────────────────────────────────────────────────────────────┘

    def run(self, state: PortfolioState) -> Dict[str, Any]:

        # ── BLOC 1 : Lecture des inputs ───────────────────────────────────────
        tickers_raw = state.get("tickers") or []
        research_brief = state.get("research_brief") or {}

        # L'utilisateur a-t-il fourni des tickers explicites ? Si oui, on respecte
        # son choix tel quel (pas de biais beta). Sinon (brief / benchmark /
        # univers par défaut), on biaisera la sélection selon le profil du mandat.
        explicit_tickers = bool(state.get("tickers"))

        # Si aucun ticker explicite mais qu'on a un brief, on demande à Claude
        # de générer une liste de tickers cohérente avec le brief.
        if not tickers_raw and research_brief:
            tickers_raw = self._generate_tickers_from_brief(research_brief) or []

        # La liste vient-elle d'un brief ? Si oui, sa longueur EST le nombre de
        # titres voulu (le brief pilote nb_idees) : le biais beta devra seulement
        # réordonner sans tronquer, pour ne pas réduire le nombre analysé.
        from_brief = (not explicit_tickers) and bool(tickers_raw)

        # Nombre de positions cible (du mandat) → dimensionne l'univers analysé.
        # On analyse ~1.5× la cible pour laisser de la marge aux HOLD/SELL : sans
        # assez de BUY, le portefeuille ne pourrait jamais atteindre la cible.
        mandate_for_size = state.get("mandate")
        nb_cible = self._target_positions(mandate_for_size)
        univers_taille = max(nb_cible + 3, int(round(nb_cible * 1.5)))

        if not tickers_raw:
            # ── CHEMIN BENCHMARK-DRIVEN ───────────────────────────────────────
            # Ni tickers explicites ni tickers issus du brief : on construit
            # l'univers à partir de la composition RÉELLE du benchmark du mandat
            # (recherche web → extraction → validation yfinance → screening LLM
            # selon mandat + conversation). Retombe sur _DEFAULT_UNIVERSE si
            # une étape échoue (cf. _build_benchmark_universe).
            benchmark_name = getattr(mandate_for_size, "benchmark", "") if mandate_for_size else ""
            briefing_messages = state.get("research_briefing_messages") or []
            if benchmark_name:
                tickers_raw = self._build_benchmark_universe(
                    benchmark_name, mandate_for_size, research_brief,
                    briefing_messages, nb_cible, univers_taille,
                )
            else:
                # Pas de benchmark dans le mandat → univers par défaut (rétro-compat).
                # Pool 2× : laisse de la matière au biais beta (tronqué ensuite à
                # univers_taille dans run()). Si pas de biais (equilibre), _apply_
                # beta_bias tronque quand même à univers_taille → count identique.
                tickers_raw = self._DEFAULT_UNIVERSE[:univers_taille * 2]

        # ── BIAIS BETA SELON LE PROFIL DU MANDAT ──────────────────────────────
        # Point d'intégration unique : oriente l'univers vers le low beta
        # (conservateur/modere) ou le high beta (dynamique/agressif). Les tickers
        # explicites de l'utilisateur sont respectés tels quels.
        # Cible de troncature selon le chemin :
        #   - brief        → len(liste) : on réordonne sans réduire le décompte.
        #   - benchmark/défaut → univers_taille : ces chemins ont sur-collecté un
        #     pool 2× exprès, on le ramène à la taille d'univers voulue.
        if not explicit_tickers and tickers_raw:
            bias_target = len(tickers_raw) if from_brief else univers_taille
            tickers_raw = self._apply_beta_bias(
                tickers_raw, mandate_for_size, bias_target
            )

        # Convertit les tickers en objets légers compatibles avec _analyze_ticker()
        # _analyze_ticker() attend un objet avec les attributs : ticker, nom, secteur,
        # geographie, raison, catalyseur. On crée un namespace simple.
        from types import SimpleNamespace
        ideas = [
            SimpleNamespace(
                ticker=t.strip().upper(),
                nom=t.strip().upper(),
                secteur=None,
                geographie=None,
                raison="Ticker fourni directement",
                catalyseur="N/D",
            )
            for t in tickers_raw if t and t.strip()
        ]

        mandate = state.get("mandate")
        # Contient : poids_max_par_position, benchmark, horizon
        # Injectés dans le prompt pour contextualiser les recommandations de poids.

        # ── BLOC 2 : Pré-condition ────────────────────────────────────────────
        if not ideas:
            return {"errors": ["Aucun ticker disponible pour la recherche"]}
        # Cas théorique : tickers_raw vide après filtrage.

        # ── BLOC 3 : Création du dossier de sortie ────────────────────────────
        os.makedirs(self.OUTPUT_DIR, exist_ok=True)
        # exist_ok=True : ne lève pas d'erreur si le dossier existe déjà.
        # Crée outputs/research/ si absent (premier run du workflow).

        # ── BLOC 4 : Extraction des paramètres du mandat ──────────────────────
        # Valeurs par défaut si mandate est None (cas théorique).
        poids_max       = mandate.poids_max_par_position if mandate else 0.07
        benchmark       = mandate.benchmark              if mandate else "MSCI World"
        horizon         = mandate.horizon                if mandate else "3-5 ans"
        profil_risque   = (mandate.profil_risque         if mandate else None) \
                          or state.get("profil_risque", "equilibre")
        # profil_risque : transmis à _analyze_ticker() pour ajuster le score_conviction
        # selon la cohérence secteur/beta du titre avec le profil du mandat.

        # Formatage des dates :
        today           = date.today().strftime("%Y%m%d")   # "20260322" → nom de fichier
        report_date_iso = date.today().strftime("%Y-%m-%d") # "2026-03-22" → dans le rapport

        # ── BLOC 5 : Initialisation des accumulateurs ─────────────────────────
        analyses: List[ResearchOutput] = []
        # Accumule les ResearchOutput Pydantic → sera retourné dans state["research"]
        # PortfolioConstructionAgent lira cette liste pour filtrer les BUY.

        research_reports: Dict[str, str] = {}
        # Associe ticker → chemin du rapport HTML généré.
        # Ex: {"NVDA": "outputs/research/NVDA_report_20260322.html"}
        # Retourné dans state["research_reports"] pour référence (non utilisé en aval).

        total = len(ideas)
        # Utilisé dans les logs "Recherche 3/15 : ASML.AS..."

        # ┌─────────────────────────────────────────────────────────────────────┐
        # │  PARALLÉLISATION — ThreadPoolExecutor (5 tickers simultanés)       │
        # │  Chaque ticker est analysé dans _analyze_ticker() indépendamment.  │
        # │  Gain : ~5× vs boucle séquentielle (I/O bound → threads efficaces) │
        # └─────────────────────────────────────────────────────────────────────┘

        results = []  # Accumulera les tuples (idx, research_out, ticker, filepath)

        # Hook de progression fourni par l'API pour mise à jour temps réel
        progress_hook = state.get("_research_progress_hook")

        with ThreadPoolExecutor(max_workers=5) as executor:
            # Soumet tous les tickers au pool en une seule passe.
            # max_workers=5 : limite pour ne pas saturer yfinance ni l'API Anthropic.
            futures = {
                executor.submit(
                    self._analyze_ticker,
                    idea, i, poids_max, benchmark, horizon, report_date_iso, today, profil_risque
                ): idea.ticker
                for i, idea in enumerate(ideas, 1)
            }

            # Récupère les résultats au fur et à mesure de leur complétion.
            # as_completed retourne les futures dans l'ordre de fin (pas de soumission).
            for future in as_completed(futures):
                res = future.result()
                results.append(res)
                # ── Mise à jour partielle après chaque ticker ──────────────────
                if progress_hook:
                    partial_sorted = sorted(results, key=lambda x: x[0])
                    partial_analyses = [r[1] for r in partial_sorted]
                    progress_hook(partial_analyses, len(results), total)

        # Rétablit l'ordre original des idées (as_completed retourne par ordre de fin).
        # Tri sur le premier élément du tuple (idx = position dans ideas).
        results.sort(key=lambda x: x[0])

        analyses         = [r[1] for r in results]
        research_reports = {r[2]: r[3] for r in results if r[3]}

        # Génération des rapports sectoriels (1 rapport par secteur)
        try:
            self._generate_sector_reports(analyses, ideas, today, report_date_iso, benchmark)
        except Exception as e:
            console.print(f"  [yellow]![/yellow]  Erreur génération rapports sectoriels : {e}")

        # ┌─────────────────────────────────────────────────────────────────────┐
        # │  RETOUR DU STATE                                                    │
        # └─────────────────────────────────────────────────────────────────────┘

        return {
            "research": analyses,
            # List[ResearchOutput] → lu par PortfolioConstructionAgent (filtre BUY)
            # et par SupervisorAgent (compte recommandations)

            "research_reports": research_reports,
            # Dict ticker → chemin HTML → stocké dans le state pour audit
            # Non consommé par les agents suivants (usage futur)

            "current_step": "portfolio",
        }


    # ╔═════════════════════════════════════════════════════════════════════════╗
    # ║  MÉTHODES PRIVÉES                                                       ║
    # ║  Chacune correspond à une responsabilité précise, isolée.              ║
    # ╚═════════════════════════════════════════════════════════════════════════╝

    # ┌─────────────────────────────────────────────────────────────────────────┐
    # │  _analyze_ticker() — ANALYSE COMPLÈTE D'UN SEUL TICKER                │
    # │  Extraite de run() pour être appelable en parallèle via ThreadPool.   │
    # │  Thread-safe : chaque appel a ses propres variables locales.          │
    # └─────────────────────────────────────────────────────────────────────────┘

    def _generate_tickers_from_brief(self, brief: Dict[str, Any]) -> List[str]:
        """
        Convertit un brief structuré (long_short, univers, sous_secteur, style, taille_capi,
        geo, nb_idees, contraintes) en liste de tickers cohérente.
        Utilise un appel LLM léger pour bénéficier de la connaissance des marchés du modèle.
        """
        try:
            user_msg = (
                "Génère UNIQUEMENT une liste JSON de tickers boursiers (forme: ['NVDA', 'ASML', ...]) "
                "qui correspondent EXACTEMENT au brief suivant. "
                "Utilise les conventions Yahoo Finance (ASML, ASML.AS, 7203.T, etc.). "
                "Aucune explication, juste la liste JSON.\n\n"
                f"BRIEF : {json.dumps(brief, ensure_ascii=False)}\n\n"
                f"Nombre attendu : {brief.get('nb_idees') or 8} tickers."
            )
            # Appel sans tool use, court
            raw = self._call_llm_with_retry(user_msg)
            if not raw:
                return []
            text = raw.strip()
            # Extraction JSON tolérante
            if "```" in text:
                text = text.split("```")[1]
                if text.lstrip().startswith("json"):
                    text = text.split("\n", 1)[1] if "\n" in text else text[4:]
                text = text.split("```")[0]
            s = text.find("[")
            e = text.rfind("]")
            if s == -1 or e <= s:
                return []
            arr = json.loads(text[s:e + 1])
            # Cap large (80) : le nombre réel est piloté par nb_idees dans le prompt,
            # lui-même dimensionné sur le nombre de positions cible du mandat (jusqu'à 50).
            return [str(t).strip().upper() for t in arr if t and isinstance(t, str)][:80]
        except Exception:
            return []

    # ┌─────────────────────────────────────────────────────────────────────────┐
    # │  SÉLECTION BENCHMARK-DRIVEN                                             │
    # │  Construit l'univers à partir de la composition réelle du benchmark    │
    # │  du mandat (recherche web), puis le screene selon mandat + conversation.│
    # └─────────────────────────────────────────────────────────────────────────┘

    def _build_benchmark_universe(
        self,
        benchmark:        str,
        mandate:          Any,
        research_brief:   Dict[str, Any],
        briefing_messages: List[dict],
        nb_cible:         int,
        univers_taille:   int,
    ) -> List[str]:
        """
        Pipeline benchmark-driven :
          1. recherche web des composantes du benchmark
          2. extraction LLM des tickers
          3. validation yfinance
          4. screening LLM (mandat + conversation)
        Retombe sur _DEFAULT_UNIVERSE à chaque étape qui échoue (rétro-compat).
        Retourne une liste de tickers (taille ~univers_taille).
        """
        # ── Étape 1 : recherche web ───────────────────────────────────────────
        web = get_benchmark_constituents(benchmark)
        if web.get("statut") != "OK" or not web.get("raw_text"):
            console.print(
                f"  [yellow]![/yellow]  Composition benchmark '{benchmark}' indisponible "
                f"({web.get('message', 'n/d')}) → univers par défaut"
            )
            return self._DEFAULT_UNIVERSE[:univers_taille]

        # ── Étape 2 : extraction LLM des tickers ──────────────────────────────
        # On extrait large (2× la taille requise) pour laisser de la marge au
        # screening et à la validation yfinance.
        univers = self._extract_tickers_from_benchmark_text(
            web["raw_text"], benchmark, nb_souhaite=univers_taille * 2
        )
        if not univers:
            console.print(
                f"  [yellow]![/yellow]  Extraction tickers benchmark vide → univers par défaut"
            )
            return self._DEFAULT_UNIVERSE[:univers_taille]

        # ── Étape 3 : validation yfinance ─────────────────────────────────────
        univers = self._validate_tickers(univers)
        if not univers:
            console.print(
                f"  [yellow]![/yellow]  Aucun ticker benchmark validé → univers par défaut"
            )
            return self._DEFAULT_UNIVERSE[:univers_taille]

        console.print(
            f"  [green]✓[/green]  Univers benchmark '{benchmark}' : "
            f"[bold]{len(univers)}[/bold] titres validés"
        )

        # ── Étape 4 : screening LLM selon mandat + conversation ───────────────
        retenus = self._screen_universe(
            univers, mandate, research_brief, briefing_messages, univers_taille
        )

        # ── Cascade finale ────────────────────────────────────────────────────
        # Si le screening n'a pas retenu assez de titres, on complète avec
        # l'univers benchmark validé, puis _DEFAULT_UNIVERSE, sans doublons.
        final = list(dict.fromkeys(retenus))  # dédup en préservant l'ordre
        # On complète jusqu'à 2× la cible : un pool plus large que univers_taille
        # laisse de la matière au biais beta (cf. _apply_beta_bias dans run()),
        # qui tronquera ensuite à univers_taille. Le count final reste identique.
        cible_pool = univers_taille * 2
        if len(final) < cible_pool:
            for t in univers + self._DEFAULT_UNIVERSE:
                if t not in final:
                    final.append(t)
                if len(final) >= cible_pool:
                    break
        return final[:cible_pool]

    def _extract_tickers_from_benchmark_text(
        self, raw_text: str, benchmark: str, nb_souhaite: int
    ) -> List[str]:
        """
        Extrait une liste de tickers Yahoo Finance propres à partir du texte web
        brut décrivant les composantes du benchmark. Même patron tolérant que
        _generate_tickers_from_brief (gestion ```json + recherche [...]).
        """
        try:
            user_msg = (
                "À partir du texte ci-dessous décrivant les principales composantes "
                f"de l'indice {benchmark}, extrais UNIQUEMENT une liste JSON de tickers "
                "boursiers (forme: ['NVDA', 'MSFT', 'NESN.SW', ...]). "
                "Utilise les conventions de symbole Yahoo Finance (suffixes .PA, .SW, "
                ".L, .T, .HK, .KS, etc. pour les places hors USA). "
                "N'invente AUCUN ticker absent du texte. Aucune explication, juste la liste JSON.\n\n"
                f"NOMBRE MAXIMUM : {nb_souhaite} tickers.\n\n"
                f"TEXTE :\n{raw_text[:6000]}"
            )
            raw = self._call_llm_with_retry(user_msg)
            if not raw:
                return []
            text = raw.strip()
            if "```" in text:
                text = text.split("```")[1]
                if text.lstrip().startswith("json"):
                    text = text.split("\n", 1)[1] if "\n" in text else text[4:]
                text = text.split("```")[0]
            s = text.find("[")
            e = text.rfind("]")
            if s == -1 or e <= s:
                return []
            arr = json.loads(text[s:e + 1])
            return [str(t).strip().upper() for t in arr if t and isinstance(t, str)][:nb_souhaite]
        except Exception:
            return []

    def _validate_tickers(self, tickers: List[str]) -> List[str]:
        """
        Garde uniquement les tickers qui renvoient un prix valide via yfinance.
        Parallélisé (même patron que _analyze_ticker). Préserve l'ordre d'entrée.
        """
        import yfinance as yf

        def _is_valid(tk: str) -> bool:
            try:
                # fast_info.last_price : attribut fiable (le .get() de FastInfo
                # renvoie None même quand l'attribut existe → on lit l'attribut).
                price = getattr(yf.Ticker(tk).fast_info, "last_price", None)
                return price is not None and price > 0
            except Exception:
                return False

        valides = set()
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(_is_valid, tk): tk for tk in tickers}
            for future in as_completed(futures):
                tk = futures[future]
                try:
                    if future.result():
                        valides.add(tk)
                except Exception:
                    pass
        # Conserve l'ordre original (les top pondérations d'abord)
        return [t for t in tickers if t in valides]

    # ┌─────────────────────────────────────────────────────────────────────────┐
    # │  _apply_beta_bias() — BIAIS DE SÉLECTION SELON LE PROFIL DE RISQUE     │
    # │  Oriente l'univers ANALYSÉ vers le low beta (mandats conservateurs) ou  │
    # │  le high beta (mandats dynamiques). Biais SOUPLE : on ne rejette jamais  │
    # │  un titre, on réordonne le pool puis on garde les univers_taille premiers│
    # │  → le NOMBRE de titres analysés ne change pas, seule la composition.     │
    # └─────────────────────────────────────────────────────────────────────────┘

    def _apply_beta_bias(
        self,
        tickers: List[str],
        mandate: Any,
        univers_taille: int,
    ) -> List[str]:
        """
        Réordonne `tickers` selon le profil de risque du mandat puis tronque à
        `univers_taille`. conservateur/modere → low beta d'abord ;
        dynamique/agressif → high beta d'abord ; equilibre/inconnu → no-op.
        Les betas sont récupérés via get_stock_info (mis en cache → réutilisés
        ensuite par _fetch_all_market_data, donc coût externe net nul).
        """
        # ── Direction du biais ────────────────────────────────────────────────
        profil = (getattr(mandate, "profil_risque", None) or "equilibre").lower()
        if profil in ("conservateur", "modere"):
            prefer_low = True
        elif profil in ("dynamique", "agressif"):
            prefer_low = False
        else:
            # equilibre / mandat absent / profil inconnu → pas de biais.
            return tickers[:univers_taille]

        if not tickers:
            return []

        # ── Récupération des betas en parallèle (même patron que _validate) ────
        # get_stock_info est caché (market_data._cached) : ces appels réchauffent
        # le cache pour _fetch_all_market_data → aucun appel externe supplémentaire.
        betas: Dict[str, Optional[float]] = {}

        def _fetch_beta(tk: str) -> Optional[float]:
            try:
                info = get_stock_info(tk)
                if isinstance(info, dict) and info.get("statut") == "OK":
                    b = info.get("beta")
                    return float(b) if b is not None else None
            except Exception:
                pass
            return None

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(_fetch_beta, tk): tk for tk in tickers}
            for future in as_completed(futures):
                tk = futures[future]
                try:
                    betas[tk] = future.result()
                except Exception:
                    betas[tk] = None

        # ── Clé de tri ────────────────────────────────────────────────────────
        # Beta manquant → sentinelle qui le repousse en FIN de l'ordre préféré
        # (jamais rejeté, mais les vrais low/high beta gagnent les premières
        # places). Tri stable : l'ordre d'origine (top pondérations) départage.
        def _sort_key(tk: str) -> float:
            b = betas.get(tk)
            if b is None:
                return float("inf") if prefer_low else float("-inf")
            return b if prefer_low else -b

        ordered = sorted(tickers, key=_sort_key)
        return ordered[:univers_taille]

    def _screen_universe(
        self,
        univers:          List[str],
        mandate:          Any,
        research_brief:   Dict[str, Any],
        briefing_messages: List[dict],
        univers_taille:   int,
    ) -> List[str]:
        """
        Sélectionne, parmi l'univers benchmark validé, les titres les plus
        pertinents au regard du mandat ET de la conversation de cadrage.
        Garde-fou anti-hallucination : intersection avec `univers`.
        """
        try:
            # ── Résumé du mandat (contraintes dures) ──────────────────────────
            mandate_resume = {}
            if mandate is not None:
                try:
                    secteurs = {
                        k: {"min": v.min, "max": v.max}
                        for k, v in (mandate.contraintes_sectorielles or {}).items()
                    }
                except Exception:
                    secteurs = {}
                mandate_resume = {
                    "profil_risque":       getattr(mandate, "profil_risque", "equilibre"),
                    "contraintes_sect":    secteurs,
                    "actifs_exclus":       getattr(mandate, "actifs_exclus", []),
                    "criteres_ESG":        getattr(mandate, "criteres_ESG", {}),
                    "nombre_positions":    getattr(mandate, "nombre_positions_cible", ""),
                }

            # ── Transcript de la conversation (même patron que le briefing PM) ─
            transcript = ""
            if briefing_messages:
                lignes = []
                for msg in briefing_messages:
                    role    = msg.get("role", "user")
                    content = (msg.get("content") or "").strip()
                    if not content:
                        continue
                    label = "PM" if role == "user" else "AGENT"
                    lignes.append(f"[{label}] {content}")
                transcript = "\n".join(lignes)

            user_msg = (
                "Tu es un analyste buy-side. Voici l'univers investissable issu du benchmark :\n"
                f"{json.dumps(univers, ensure_ascii=False)}\n\n"
                f"MANDAT (contraintes dures) :\n{json.dumps(mandate_resume, ensure_ascii=False)}\n\n"
                f"BRIEF STRUCTURÉ :\n{json.dumps(research_brief or {}, ensure_ascii=False)}\n\n"
                + (f"DIRECTIVES PM (conversation de cadrage) :\n"
                   f"--- DÉBUT ---\n{transcript}\n--- FIN ---\n\n" if transcript else "")
                + f"Sélectionne EXACTEMENT {univers_taille} tickers DE L'UNIVERS CI-DESSUS "
                "(ne propose AUCUN ticker absent de la liste), les plus pertinents au regard "
                "du mandat ET des directives. Respecte les exclusions sectorielles/actifs. "
                "Retourne UNIQUEMENT une liste JSON ['NVDA', ...]. Aucune explication."
            )

            raw = self._call_llm_with_retry(user_msg)
            if not raw:
                return univers[:univers_taille]
            text = raw.strip()
            if "```" in text:
                text = text.split("```")[1]
                if text.lstrip().startswith("json"):
                    text = text.split("\n", 1)[1] if "\n" in text else text[4:]
                text = text.split("```")[0]
            s = text.find("[")
            e = text.rfind("]")
            if s == -1 or e <= s:
                return univers[:univers_taille]
            arr = json.loads(text[s:e + 1])
            choisis = [str(t).strip().upper() for t in arr if t and isinstance(t, str)]
            # Garde-fou : ne garder que les tickers réellement dans l'univers validé.
            univers_set = set(univers)
            retenus = [t for t in choisis if t in univers_set]
            return retenus[:univers_taille] if retenus else univers[:univers_taille]
        except Exception:
            # En cas d'échec du screening, on rend l'univers benchmark validé tronqué.
            return univers[:univers_taille]

    def _analyze_ticker(
        self,
        idea:           Any,
        idx:            int,   # Position originale dans ideas (pour rétablir l'ordre)
        poids_max:      float,
        benchmark:      str,
        horizon:        str,
        report_date_iso: str,
        today:          str,
        profil_risque:  str = "equilibre",  # Profil du mandat pour ajuster le score_conviction
    ):
        """Analyse un ticker de bout en bout et retourne (idx, ResearchOutput, ticker, filepath)."""

        console.print(f"  [yellow]⟳[/yellow]  Recherche {idx} : [bold]{idea.ticker}[/bold] ...")

        # ── SOUS-ÉTAPE 1 : Pre-fetch données marché ───────────────────────────
        market_pkg  = self._fetch_all_market_data(idea.ticker)

        # ── SOUS-ÉTAPE 2 : Formatage texte pour le prompt ─────────────────────
        market_text = self._format_market_data(market_pkg)

        # ── SOUS-ÉTAPE 3 : Construction du prompt ─────────────────────────────
        user_msg = REPORT_NARRATIVE_PROMPT.format(
            ticker           = idea.ticker,
            nom              = idea.nom        or idea.ticker,
            secteur          = idea.secteur    or "N/D",
            geographie       = idea.geographie or "N/D",
            raison           = idea.raison     or "N/D",
            catalyseur       = idea.catalyseur or "N/D",
            report_date      = report_date_iso,
            market_data_text = market_text,
            poids_max        = f"{poids_max:.0%}",
            benchmark        = benchmark,
            horizon          = horizon,
            profil_risque    = profil_risque,
        )

        # ── SOUS-ÉTAPE 4 : Appel Claude ───────────────────────────────────────
        raw = self._call_llm_with_retry(user_msg)

        if not raw or not raw.strip():
            console.print(f"  [yellow]![/yellow]  [bold]{idea.ticker}[/bold] : réponse vide, fallback")
            return (idx, self._fallback_research(idea, "reponse vide"), idea.ticker, None)

        # ── SOUS-ÉTAPE 5 : Parsing JSON ───────────────────────────────────────
        try:
            claude_data = self._parse_json(raw)
        except Exception as e:
            console.print(f"  [yellow]![/yellow]  [bold]{idea.ticker}[/bold] : erreur JSON ({e})")
            return (idx, self._fallback_research(idea, str(e)), idea.ticker, None)

        # ── SOUS-ÉTAPE 6 : Construction ResearchOutput Pydantic ───────────────
        try:
            research_out = self._build_research_output(claude_data, idea, market_pkg)
        except Exception as e:
            console.print(f"  [yellow]![/yellow]  [bold]{idea.ticker}[/bold] : erreur ResearchOutput ({e})")
            research_out = self._fallback_research(idea, str(e))

        # ── SOUS-ÉTAPE 7 : Construction du dict rapport HTML ──────────────────
        report_data = self._build_report_data(claude_data, market_pkg, idea, report_date_iso)

        # ── SOUS-ÉTAPE 8 : Génération et sauvegarde HTML ──────────────────────
        filepath = None
        try:
            html_content = generate_company_report(report_data)
            filename     = f"{idea.ticker}_report_{today}.html"
            filepath     = os.path.join(self.OUTPUT_DIR, filename)
            with open(filepath, "w", encoding="utf-8") as fh:
                fh.write(html_content)
            console.print(f"  [green]✓[/green]  [bold]{idea.ticker}[/bold] → [dim]{os.path.relpath(filepath)}[/dim]")
        except Exception as e:
            console.print(f"  [yellow]![/yellow]  [bold]{idea.ticker}[/bold] : erreur HTML ({e})")

        return (idx, research_out, idea.ticker, filepath)

    @staticmethod
    def _make_sector_slug(name: str) -> str:
        """Converts sector name to a safe ASCII filename slug."""
        import unicodedata as _ud
        import re as _re
        nfkd = _ud.normalize('NFKD', name)
        ascii_str = nfkd.encode('ascii', 'ignore').decode('ascii')
        return _re.sub(r'[^a-z0-9]+', '_', ascii_str.lower()).strip('_') or 'autre'

    def _generate_sector_reports(
        self,
        analyses: list,
        ideas: list,
        today: str,
        report_date_iso: str,
        benchmark: str,
    ) -> None:
        """
        Génère un rapport HTML par secteur en appelant Claude.
        Appelé après que toutes les analyses entreprises sont terminées.
        """
        # Construire le mapping ticker → secteur depuis les ideas
        ticker_to_sector = {}
        ticker_to_idea   = {}
        for idea in ideas:
            ticker_to_sector[idea.ticker] = idea.secteur or "Autre"
            ticker_to_idea[idea.ticker]   = idea

        # Grouper les analyses par secteur
        sectors: dict = {}
        for r in analyses:
            sect = ticker_to_sector.get(r.ticker, "Autre")
            if sect not in sectors:
                sectors[sect] = []
            sectors[sect].append(r)

        if not sectors:
            return

        console.print(f"  [cyan]→[/cyan]  Génération de {len(sectors)} rapport(s) sectoriel(s)...")

        for sector_name, sector_analyses in sectors.items():
            try:
                # Construire le résumé des entreprises pour le prompt
                lines = []
                for r in sector_analyses:
                    val = r.valorisation
                    upside = val.upside_potentiel if val.upside_potentiel else "N/D"
                    per    = val.PER_estime_NTM   if val.PER_estime_NTM   else "N/D"
                    lines.append(
                        f"• {r.ticker} ({r.nom}) | {r.recommandation} | Score: {r.score_conviction}/100 | "
                        f"PER NTM: {per} | Upside: {upside}\n"
                        f"  Thèse: {r.these_investissement[:150] if r.these_investissement else 'N/D'}\n"
                        f"  Risques: {', '.join(r.risques_cles[:3]) if r.risques_cles else 'N/D'}"
                    )
                companies_summary = "\n\n".join(lines)

                # Appel LLM
                user_msg = SECTOR_REPORT_PROMPT.format(
                    sector_name      = sector_name,
                    report_date      = report_date_iso,
                    benchmark        = benchmark,
                    companies_summary= companies_summary,
                )
                raw = self._call_llm_with_retry(user_msg)
                if not raw or not raw.strip():
                    console.print(f"  [yellow]![/yellow]  Secteur {sector_name} : réponse vide")
                    continue

                claude_data = self._parse_json(raw)

                # Métriques agrégées depuis les analyses
                avg_score    = round(sum(r.score_conviction for r in sector_analyses) / len(sector_analyses))
                total_weight = sum(r.poids_suggere_initial for r in sector_analyses)
                buy_count    = sum(1 for r in sector_analyses if r.recommandation.upper() == "BUY")

                # Top picks (entreprises avec meilleur score)
                top = sorted(sector_analyses, key=lambda x: x.score_conviction, reverse=True)[:3]
                top_picks_str = ", ".join(f"{r.ticker} ({r.recommandation})" for r in top)

                # Data pour le HTML
                report_data = {
                    "ticker"                : self._make_sector_slug(sector_name).upper(),
                    "sector_name"           : sector_name,
                    "report_date"           : report_date_iso,
                    "source"                : "AlphaSwarm Sector Research",
                    "sector_overview"       : claude_data.get("sector_overview", ""),
                    "key_drivers"           : claude_data.get("key_drivers", ""),
                    "valuation_analysis"    : claude_data.get("valuation_analysis", ""),
                    "top_picks"             : claude_data.get("top_picks", top_picks_str),
                    "risk_factors"          : claude_data.get("risk_factors", ""),
                    "recommended_allocation": claude_data.get("recommended_allocation", "Neutre"),
                    "sector_pe_median"      : claude_data.get("sector_pe_median"),
                    "sector_market_cap"     : None,
                    "sector_perf_ytd"       : None,
                    "sector_series"         : [],
                    # Métriques agrégées supplémentaires (passées dans top_picks pour affichage)
                    "_avg_score"            : avg_score,
                    "_total_weight_pct"     : round(total_weight * 100, 1),
                    "_buy_count"            : buy_count,
                    "_nb_companies"         : len(sector_analyses),
                }

                html_content = generate_sector_report(report_data)
                slug     = self._make_sector_slug(sector_name)
                filename = f"sector_{slug}_{today}.html"
                filepath = os.path.join(self.OUTPUT_DIR, filename)
                with open(filepath, "w", encoding="utf-8") as fh:
                    fh.write(html_content)
                console.print(f"  [green]✓[/green]  Secteur {sector_name} → [dim]{os.path.relpath(filepath)}[/dim]")

            except Exception as e:
                console.print(f"  [yellow]![/yellow]  Secteur {sector_name} : erreur ({e})")

    # ┌─────────────────────────────────────────────────────────────────────────┐
    # │  _fetch_all_market_data() — PRE-FETCH DES DONNÉES YFINANCE             │
    # │  Appelle les 5 fonctions de market_data.py pour un ticker donné.       │
    # │  Chaque appel est dans son propre try/except pour isolation d'erreurs. │
    # └─────────────────────────────────────────────────────────────────────────┘

    def _fetch_all_market_data(self, ticker: str) -> Dict[str, Any]:
        """Pre-fetche toutes les donnees marche pour un ticker (appels parallelises)."""

        # ── Initialisation du package ─────────────────────────────────────────
        pkg: Dict[str, Any] = {"ticker": ticker}
        # pkg sera enrichi avec les clés : info, financials, price_history,
        # annual_financials, price_series, fmp_financials, fmp_ratios,
        # fmp_analyst, web_research, sec_report. Chacune est un dict.

        # ── Helper local : exécute fn et capture toute erreur en fallback ─────
        # Garantit que chaque clé du pkg existe toujours, avec le MÊME fallback
        # qu'avant la parallélisation ({"statut": "ERREUR", "message": ...}).
        def _safe(fn, *args):
            try:
                return fn(*args)
            except Exception as e:
                return {"statut": "ERREUR", "message": str(e)}

        # ── Appel 1 (SÉRIE) : Infos générales ─────────────────────────────────
        # Fait en premier — séparément — pour deux raisons :
        #   1. get_web_research a besoin du "nom" (seule dépendance interne).
        #   2. réchauffe le cache beta (réutilisé par _apply_beta_bias).
        # Retourne : prix actuel, market cap, secteur, volume 30j, beta.
        pkg["info"] = _safe(get_stock_info, ticker)
        nom = pkg.get("info", {}).get("nom", ticker)

        # ── Appels 2-10 (PARALLÈLE) : indépendants entre eux ──────────────────
        # Chaque appel est un I/O bloquant (yfinance / FMP / Tavily / SEC).
        # On les exécute simultanément : la latence passe de "somme" à "max".
        # max_workers=6 : compromis vitesse / throttling (le pool externe de
        # run() tourne déjà à 5 → ~30 threads I/O max au pire, acceptable).
        tasks = {
            # clé pkg            : (fonction, *args)
            "financials":        (get_financials, ticker),
            "price_history":     (get_price_history, ticker, "1y"),
            "annual_financials": (get_annual_financials, ticker),
            "price_series":      (get_price_series, ticker, "^GSPC", "1y"),
            "fmp_financials":    (get_fmp_historical_financials, ticker),
            "fmp_ratios":        (get_fmp_historical_ratios, ticker),
            "fmp_analyst":       (get_fmp_analyst_targets, ticker),
            "web_research":      (get_web_research, ticker, nom),
            "sec_report":        (get_sec_annual_report, ticker),
        }

        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = {
                executor.submit(_safe, fn, *args): key
                for key, (fn, *args) in tasks.items()
            }
            for future in as_completed(futures):
                key = futures[future]
                pkg[key] = future.result()
                # _safe ne lève jamais → future.result() rend toujours un dict.

        return pkg
        # Retourne un dict avec ticker + 9 sources de données marché.
        # Toujours retourné même si toutes les sources ont échoué.

    # ┌─────────────────────────────────────────────────────────────────────────┐
    # │  _format_market_data() — FORMATAGE TEXTE POUR LE PROMPT LLM           │
    # │  Convertit le dict de données marché en texte lisible par Claude.     │
    # └─────────────────────────────────────────────────────────────────────────┘

    def _format_market_data(self, pkg: Dict[str, Any]) -> str:
        """Formate le package de donnees marche en texte pour le prompt LLM."""

        lines: List[str] = []
        # Accumulateur de lignes texte. Rejoint avec "\n" à la fin.

        # ── Section 1 : Données générales ─────────────────────────────────────
        info = pkg.get("info", {})
        if info.get("statut") != "ERREUR":
            # On n'affiche les données que si l'appel a réussi.
            # Valeurs manquantes → "N/D" grâce à get(key, "N/D").
            lines.append(f"Prix actuel       : {info.get('prix_actuel', 'N/D')}")
            lines.append(f"Market Cap (Mrd$) : {info.get('capitalisation_mrd_usd', 'N/D')}")
            lines.append(f"Volume moyen 30j  : {info.get('volume_moyen_30j', 'N/D')}")
            lines.append(f"Secteur           : {info.get('secteur', 'N/D')}")
            lines.append(f"Beta              : {info.get('beta', 'N/D')}")
            # Beta permet au LLM d'évaluer le risque systématique du titre.

        # ── Section 2 : Ratios financiers ─────────────────────────────────────
        fins = pkg.get("financials", {})
        if fins.get("statut") != "ERREUR":
            lines.append(f"P/E TTM           : {fins.get('PER_ttm', 'N/D')}")
            lines.append(f"P/E Forward       : {fins.get('PER_forward', 'N/D')}")
            # P/E Forward = P/E sur les bénéfices estimés → clé pour la valorisation
            lines.append(f"EV/EBITDA         : {fins.get('EV_EBITDA', 'N/D')}")
            lines.append(f"Marge brute       : {fins.get('marge_brute', 'N/D')}")
            lines.append(f"Marge operationnelle: {fins.get('marge_operationnelle', 'N/D')}")
            lines.append(f"Marge nette       : {fins.get('marge_nette', 'N/D')}")
            lines.append(f"ROE               : {fins.get('ROE', 'N/D')}")
            # ROE = Return on Equity → qualité de la gestion du capital
            lines.append(f"ROA               : {fins.get('ROA', 'N/D')}")
            lines.append(f"Croissance revenus: {fins.get('croissance_revenus_yoy', 'N/D')}")
            lines.append(f"EPS TTM           : {fins.get('eps_ttm', 'N/D')}")
            lines.append(f"EPS Forward       : {fins.get('eps_forward', 'N/D')}")
            lines.append(f"PB Ratio          : {fins.get('PB_ratio', 'N/D')}")
            # PB = Price to Book → valeur comptable vs valeur de marché
            lines.append(f"Rendement dividende: {fins.get('dividend_yield', 'N/D')}")

        # ── Section 3 : Performance de prix ───────────────────────────────────
        hist = pkg.get("price_history", {})
        if hist.get("statut") != "ERREUR":
            lines.append(f"Perf 1 an         : {hist.get('performance_periode', 'N/D')}")
            # Ex: 0.4521 → le LLM interprétera comme "+45.2% sur 1 an"
            lines.append(f"Volatilite annualisee: {hist.get('volatilite_annualisee', 'N/D')}")
            lines.append(f"Prix debut periode: {hist.get('prix_debut', 'N/D')}")
            lines.append(f"Prix fin periode  : {hist.get('prix_fin', 'N/D')}")

        # ── Section 4 : Historique financier annuel (FMP prioritaire) ───────────
        fmp_fins = pkg.get("fmp_financials", {})
        ann      = pkg.get("annual_financials", {})

        # FMP si disponible, sinon fallback sur yfinance
        source_annees = (
            fmp_fins.get("annees", []) if fmp_fins.get("statut") == "OK"
            else ann.get("annees", [])
        )
        if source_annees:
            lines.append("Historique financier (5 ans) :")
            for yr in source_annees:
                lines.append(
                    f"  {yr.get('annee', '?')} | "
                    f"Rev: {yr.get('revenue_mio', 'N/D')} Mio$ "
                    f"| NI: {yr.get('net_income_mio', 'N/D')} Mio$ "
                    f"| EPS: {yr.get('eps', 'N/D')} "
                    f"| EBIT margin: {yr.get('ebit_margin', 'N/D')}"
                )

        # ── Section 5 : Ratios historiques FMP (P/E, EV/EBITDA, ROE par année) ─
        fmp_ratios = pkg.get("fmp_ratios", {})
        if fmp_ratios.get("statut") == "OK":
            ratio_annees = fmp_ratios.get("annees", [])
            if ratio_annees:
                lines.append("Ratios historiques :")
                for yr in ratio_annees:
                    lines.append(
                        f"  {yr.get('annee', '?')} | "
                        f"P/E: {yr.get('pe_ratio', 'N/D')} "
                        f"| EV/EBITDA: {yr.get('ev_ebitda', 'N/D')} "
                        f"| ROE: {yr.get('roe', 'N/D')} "
                        f"| PB: {yr.get('pb_ratio', 'N/D')}"
                    )

        # ── Section 6 : Consensus analystes FMP ───────────────────────────────
        fmp_analyst = pkg.get("fmp_analyst", {})
        if fmp_analyst.get("statut") == "OK":
            lines.append(
                f"Consensus analystes   : "
                f"Bas {fmp_analyst.get('prix_cible_bas', 'N/D')} | "
                f"Moyen {fmp_analyst.get('prix_cible_moyen', 'N/D')} | "
                f"Haut {fmp_analyst.get('prix_cible_haut', 'N/D')} "
                f"({fmp_analyst.get('nb_analystes', 'N/D')} analystes)"
            )

        # ── Section 7 : Recherche web Tavily ──────────────────────────────────
        web = pkg.get("web_research", {})
        web_text = format_web_research_for_prompt(web)
        if web_text:
            lines.append("")
            lines.append(web_text)

        # ── Section 8 : SEC EDGAR 10-K ─────────────────────────────────────────
        sec = pkg.get("sec_report", {})
        sec_text = format_sec_for_prompt(sec)
        if sec_text:
            lines.append("")
            lines.append(sec_text)

        # ── Retour ────────────────────────────────────────────────────────────
        return "\n".join(lines) if lines else "Donnees non disponibles"
        # "\n".join : concatene toutes les lignes avec un retour à la ligne.
        # Fallback : si TOUTES les sources ont échoué → texte minimal.

    # ┌─────────────────────────────────────────────────────────────────────────┐
    # │  _build_research_output() — CONSTRUCTION DU RESEARCHOUTPUT PYDANTIC    │
    # │  Extrait les champs utiles au workflow depuis la réponse Claude.       │
    # │  N'inclut PAS les sections narratives (trop volumineuses).             │
    # └─────────────────────────────────────────────────────────────────────────┘

    def _build_research_output(
        self,
        claude_data: Dict[str, Any],  # JSON parsé retourné par Claude
        idea: Any,                    # IdeaOutput de référence (fallbacks)
        market_pkg: Optional[Dict[str, Any]] = None,  # données marché pré-fetchées
    ) -> ResearchOutput:
        """Construit un ResearchOutput Pydantic depuis la reponse Claude."""

        # ── Beta réel (depuis les données marché yfinance) ────────────────────
        # Capturé dans ResearchOutput pour cohérence sélection/risque et rapports.
        # None si données absentes/erreur → champ par défaut None (rétro-compatible).
        info = (market_pkg or {}).get("info", {})
        beta = info.get("beta") if isinstance(info, dict) and info.get("statut") == "OK" else None

        # ── Normalisation de la valorisation ──────────────────────────────────
        val_raw = claude_data.get("valorisation", {})
        # Claude retourne valorisation sous forme de dict imbriqué.
        # Ex: {"methode_principale": "DCF", "PER_estime_NTM": "32x", ...}

        if not isinstance(val_raw, dict):
            val_raw = {}
        # Garde-fou : si Claude retourne valorisation en string ou None → dict vide.
        # Pydantic de Valorisation utilisera ses valeurs par défaut ("", None...).

        # ── Cohérence rating ↔ recommandation ─────────────────────────────────
        # rating       : champ visuel HTML  ("strongBuy" / "Buy" / "Hold" / "Sell")
        # recommandation : champ workflow   ("BUY" / "HOLD" / "SELL")
        # Problème : Claude peut retourner rating="strongBuy" et recommandation="HOLD"
        # → rapport HTML dit "Strong Buy" mais PortfolioAgent ignore le titre.
        # Solution : dériver recommandation depuis rating quand ils sont incohérents.
        _RATING_MAP = {
            "strongBuy": "BUY",
            "Buy":       "BUY",
            "Hold":      "HOLD",
            "Sell":      "SELL",
        }
        rating         = claude_data.get("rating", "Hold")
        recommandation = claude_data.get("recommandation", "HOLD").upper()

        recommandation_from_rating = _RATING_MAP.get(rating)
        if recommandation_from_rating and recommandation_from_rating != recommandation:
            # Incohérence détectée → on aligne sur rating (plus granulaire)
            console.print(
                f"  [dim]⚠ {claude_data.get('ticker', '?')} : "
                f"rating={rating} ≠ recommandation={recommandation} "
                f"→ corrigé en {recommandation_from_rating}[/dim]"
            )
            recommandation = recommandation_from_rating

        # ── Construction du ResearchOutput ────────────────────────────────────
        return ResearchOutput(
            ticker = claude_data.get("ticker", idea.ticker),
            # Préfère le ticker retourné par Claude (peut différer de idea.ticker
            # si Claude l'a corrigé, ex: "BNP" → "BNP.PA")

            nom = claude_data.get("nom", idea.nom or idea.ticker),
            # Nom complet de la société. Fallback sur idea.nom, puis sur le ticker.

            beta = beta,
            # Beta réel du titre (yfinance). Sert au biais de sélection par profil
            # et est lisible par RiskManagementAgent / les rapports. None si absent.

            executive_summary = claude_data.get("executive_summary", ""),
            # 5 lignes : reco + upside + raisons clés + risque principal (PM quick read)

            these_investissement = claude_data.get("these_investissement", ""),
            # 1 phrase résumant la thèse. Stocké dans ResearchOutput mais
            # non utilisé en aval (sert pour les rapports HTML et logs).

            valorisation = val_raw,
            # model.research.ResearchOutput.model_post_init convertit ce dict
            # en objet Valorisation si nécessaire.

            risques_cles = claude_data.get("risques_cles", []),
            # Ex: ["Risque réglementaire IA", "Concurrence AMD/Intel", "Valorisation tendue"]
            # Non utilisé par PortfolioAgent mais stocké pour le rapport HTML.

            catalyseurs = claude_data.get("catalyseurs", []),
            # Ex: ["Lancement GB200", "Expansion data centers", "Résultats Q2"]

            score_conviction = int(claude_data.get("score_conviction", 50)),
            # int() : force la conversion si Claude retourne un float (ex: 75.0 → 75)
            # Range 0-100 défini dans le prompt.
            # Utilisé par PortfolioAgent pour pondérer les positions.

            recommandation = recommandation,
            # BUY / HOLD / SELL — aligné sur rating si incohérence détectée.
            # C'est LE champ critique : PortfolioAgent ne garde que les BUY.

            poids_suggere_initial = float(claude_data.get("poids_suggere_initial", 0.03)),
            # float() : force la conversion (ex: "0.05" → 0.05)
            # Suggestion de poids initial. PortfolioAgent peut l'ajuster.

            donnees_marche = {},
            # On ne stocke pas les données brutes yfinance dans ResearchOutput.
            # Elles sont volumineuses et ne servent pas aux agents suivants.
            # Elles sont utilisées uniquement dans _build_report_data (HTML).
        )

    # ┌─────────────────────────────────────────────────────────────────────────┐
    # │  _build_report_data() — ASSEMBLAGE DU DICT POUR LE RAPPORT HTML        │
    # │  Combine claude_data + market_pkg en un dict plat pour le template HTML.│
    # └─────────────────────────────────────────────────────────────────────────┘

    def _build_report_data(
        self,
        claude_data: Dict[str, Any],  # JSON parsé de Claude (sections narratives + rating)
        market_pkg:  Dict[str, Any],  # Package de données yfinance du ticker
        idea:        Any,             # IdeaOutput (pour le ticker de référence)
        report_date: str,             # "2026-03-22" (format ISO pour l'affichage)
    ) -> Dict[str, Any]:
        """Assemble le dict complet passe a generate_company_report."""

        # ── BLOC 1 : Extraction des sous-dicts du package marché ──────────────
        info = market_pkg.get("info", {})             # Prix, market cap, secteur
        fins = market_pkg.get("financials", {})       # Ratios financiers
        ann  = market_pkg.get("annual_financials", {}) # Historique annuel + ratios courants
        ps   = market_pkg.get("price_series", {})     # Série normalisée base 100
        hist = market_pkg.get("price_history", {})    # Performance + volatilité (non utilisé ici)

        # ── BLOC 2 : Informations de base du titre ────────────────────────────
        ticker       = idea.ticker
        company_name = claude_data.get("nom") or info.get("nom") or ticker
        # Priorité : nom de Claude > nom de yfinance > ticker
        # Claude retourne parfois un nom plus propre ("ASML Holding NV" vs "ASML")

        # ── BLOC 3 : Données de marché courantes ──────────────────────────────
        closing_price = info.get("prix_actuel")
        # Prix de clôture actuel. Ex: 890.12 USD
        # Affiché dans la sidebar "Key Data" du rapport HTML.

        market_cap_bn = info.get("capitalisation_mrd_usd")
        # Capitalisation en milliards USD. Ex: 2190.5 (= 2 190 Mrd$)

        # ── BLOC 4 : Ratios financiers courants ───────────────────────────────
        pe_ratio = fins.get("PER_ttm")        # P/E Trailing 12 months. Ex: 35.2
        eps_ttm  = fins.get("eps_ttm")        # EPS TTM. Ex: 25.3 USD/action
        bvps     = ann.get("book_value_per_share")  # Valeur comptable par action

        # ── BLOC 5 : Données 52 semaines et volume (depuis le pre-fetch) ─────────
        # Ces champs sont désormais inclus dans get_stock_info() → pkg["info"].
        # Plus d'appel yfinance supplémentaire ici.
        week_52_low  = info.get("semaine_52_bas")
        week_52_high = info.get("semaine_52_haut")

        avg_vol_shares = info.get("volume_moyen_30j", 0) or 0
        avg_daily_vol = (
            round(avg_vol_shares * (closing_price or 0) / 1e6, 1)
            if closing_price else None
        )
        # Formule : volume actions × prix unitaire = volume USD
        # / 1e6 : convertit en millions USD. Ex: 5.2 = 5.2 M USD/jour

        # ── BLOC 6 : Construction des données pour les tableaux et graphiques ──

        fmp_fins   = market_pkg.get("fmp_financials", {})
        fmp_ratios = market_pkg.get("fmp_ratios", {})
        financial_metrics = self._build_financial_metrics(ann, fins, fmp_fins, fmp_ratios)
        # Construit le tableau financier historique : une ligne par année
        # avec Revenue, Net Income, EPS, EBIT margin, ROE, P/E, EV/EBITDA, PB

        price_series = ps.get("series", []) if ps.get("statut") == "OK" else []
        # Série temporelle normalisée base 100 pour le graphique "Share Performance"
        # ~24 points sur 1 an (sous-échantillonnage dans get_price_series)
        # [] si l'appel yfinance a échoué → graphique non affiché dans le HTML

        pe_eps_series = self._build_pe_eps_series(ann, fins, fmp_fins, fmp_ratios)
        # Série P/E et EPS par année pour le graphique de la sidebar

        # ── BLOC 7 : Assemblage du dict complet ──────────────────────────────
        # Ce dict est directement passé à generate_company_report() qui le
        # utilise pour remplir le template HTML. Chaque clé correspond à un
        # élément visuel du rapport institutionnel.
        return {
            # ── Identité du rapport ───────────────────────────────────────────
            "ticker":       ticker,
            "company_name": company_name,
            "report_date":  report_date,     # "2026-03-22"
            "source":       "AlphaSwarm Research",

            # ── 5 sections narratives générées par Claude ─────────────────────
            "executive_summary":   claude_data.get("executive_summary", ""),
            "income_summary":      claude_data.get("income_summary", ""),
            # Revenus, marges, croissance (200-300 mots)
            "business_highlights": claude_data.get("business_highlights", ""),
            # Avantages compétitifs, pipeline, points forts (200-300 mots)
            "company_situation":   claude_data.get("company_situation", ""),
            # Positionnement concurrentiel, stratégie (200-300 mots)
            "risk_assessment":     claude_data.get("risk_assessment", ""),
            # Risques clés : macro, concurrence, réglementaires (150-200 mots)

            # ── Sidebar "Key Data" ────────────────────────────────────────────
            "rating":           claude_data.get("rating", "Hold"),
            # "strongBuy" / "Buy" / "Hold" / "Sell" → couleur de l'indicateur
            "target_price_low":  claude_data.get("target_price_low"),
            "target_price_high": claude_data.get("target_price_high"),
            "avg_daily_vol":     avg_daily_vol,   # En millions USD
            "closing_price":     closing_price,   # Prix de clôture en USD
            "market_cap":        market_cap_bn,   # Capitalisation en Mrd USD
            "week_52_low":       week_52_low,     # Plus bas 52 semaines
            "week_52_high":      week_52_high,    # Plus haut 52 semaines
            "bvps":              bvps,            # Book Value Per Share
            "pe_ratio":          pe_ratio,        # P/E TTM
            "eps_ttm":           eps_ttm,         # EPS sur 12 mois glissants

            # ── Tableaux et graphiques ────────────────────────────────────────
            "financial_metrics": financial_metrics,  # Tableau historique annuel
            "price_series":      price_series,        # Graphique "Share Performance"
            "pe_eps_series":     pe_eps_series,       # Graphique PE/EPS sidebar
        }

    # ┌─────────────────────────────────────────────────────────────────────────┐
    # │  _build_financial_metrics() — TABLEAU FINANCIER HISTORIQUE             │
    # │  Construit une ligne par année pour le tableau HTML du rapport.        │
    # └─────────────────────────────────────────────────────────────────────────┘

    def _build_financial_metrics(
        self,
        ann:        Dict[str, Any],  # annual_financials yfinance (fallback)
        fins:       Dict[str, Any],  # financials yfinance (ratios TTM)
        fmp_fins:   Dict[str, Any] = None,  # FMP income statement historique
        fmp_ratios: Dict[str, Any] = None,  # FMP ratios historiques
    ) -> List[Dict[str, Any]]:
        """Construit la liste de metriques annuelles pour le tableau HTML."""

        # ── Source principale : FMP si disponible, sinon yfinance ─────────────
        fmp_fins   = fmp_fins   or {}
        fmp_ratios = fmp_ratios or {}

        fin_annees   = fmp_fins.get("annees",   []) if fmp_fins.get("statut")   == "OK" else ann.get("annees", [])
        ratio_annees = fmp_ratios.get("annees", []) if fmp_ratios.get("statut") == "OK" else []

        # Construit un index des ratios par année pour la jointure ci-dessous
        # Ex: {"2023": {"pe_ratio": 45.2, "roe": 0.82, ...}, ...}
        ratio_by_year = {yr.get("annee"): yr for yr in ratio_annees}

        metrics: List[Dict[str, Any]] = []

        for yr in reversed(fin_annees):
            annee  = yr.get("annee", "?")
            ratios = ratio_by_year.get(annee, {})
            # ratios = dict des ratios pour cette année (vide si FMP ratios absent)

            row: Dict[str, Any] = {
                "year":        annee,
                "revenue":     yr.get("revenue_mio"),
                "net_income":  yr.get("net_income_mio"),
                "eps":         yr.get("eps"),           # Disponible via FMP
                "ebit_margin": yr.get("ebit_margin"),
                "roe":         ratios.get("roe"),       # Disponible via FMP ratios
                "pe_ratio":    ratios.get("pe_ratio"),  # Disponible via FMP ratios
                "ev_ebitda":   ratios.get("ev_ebitda"), # Disponible via FMP ratios
                "pb_ratio":    ratios.get("pb_ratio"),  # Disponible via FMP ratios
            }
            metrics.append(row)

        # ── Fallback TTM si aucune donnée historique ───────────────────────────
        if not metrics:
            metrics.append({
                "year":        "TTM",
                "revenue":     None,
                "net_income":  None,
                "eps":         fins.get("eps_ttm"),
                "ebit_margin": fins.get("marge_operationnelle"),
                "roe":         fins.get("ROE"),
                "pe_ratio":    fins.get("PER_ttm"),
                "ev_ebitda":   fins.get("EV_EBITDA"),
                "pb_ratio":    fins.get("PB_ratio"),
            })
        else:
            # Enrichit la dernière ligne avec les ratios TTM courants si manquants
            last = metrics[-1]
            last["eps"]      = last["eps"]      or ann.get("eps_ttm")  or fins.get("eps_ttm")
            last["roe"]      = last["roe"]      or ann.get("roe")       or fins.get("ROE")
            last["pe_ratio"] = last["pe_ratio"] or ann.get("pe_ttm")   or fins.get("PER_ttm")
            last["ev_ebitda"]= last["ev_ebitda"]or ann.get("ev_ebitda")or fins.get("EV_EBITDA")
            last["pb_ratio"] = last["pb_ratio"] or ann.get("pb_ratio") or fins.get("PB_ratio")

        return metrics

    # ┌─────────────────────────────────────────────────────────────────────────┐
    # │  _build_pe_eps_series() — SÉRIE PE/EPS POUR GRAPHIQUE SIDEBAR          │
    # │  Construit une liste de points {year, pe, eps} pour la sidebar HTML.  │
    # └─────────────────────────────────────────────────────────────────────────┘

    def _build_pe_eps_series(
        self,
        ann:        Dict[str, Any],
        fins:       Dict[str, Any],
        fmp_fins:   Dict[str, Any] = None,
        fmp_ratios: Dict[str, Any] = None,
    ) -> List[Dict[str, Any]]:
        """Construit la serie PE/EPS pour le graphique de la sidebar."""

        fmp_fins   = fmp_fins   or {}
        fmp_ratios = fmp_ratios or {}

        fin_annees   = fmp_fins.get("annees",   []) if fmp_fins.get("statut")   == "OK" else ann.get("annees", [])
        ratio_annees = fmp_ratios.get("annees", []) if fmp_ratios.get("statut") == "OK" else []
        ratio_by_year = {yr.get("annee"): yr for yr in ratio_annees}

        series: List[Dict[str, Any]] = []

        # ── Étape 1 : Points historiques avec données réelles FMP ────────────
        for yr in reversed(fin_annees):
            annee  = yr.get("annee", "?")
            ratios = ratio_by_year.get(annee, {})
            series.append({
                "year": annee,
                "pe":   ratios.get("pe_ratio"),  # Réel via FMP (None si yfinance)
                "eps":  yr.get("eps"),            # Réel via FMP (None si yfinance)
            })

        # ── Étape 2 : Ajout du point TTM ──────────────────────────────────────
        ttm_eps = ann.get("eps_ttm") or fins.get("eps_ttm")
        ttm_pe  = ann.get("pe_ttm")  or fins.get("PER_ttm")
        if ttm_eps or ttm_pe:
            series.append({"year": "TTM", "pe": ttm_pe, "eps": ttm_eps})
        # Le point TTM est le seul avec des valeurs réelles (EPS et P/E courants).

        # ── Étape 3 : Nettoyage des points sans valeur ────────────────────────
        series = [s for s in series if s.get("pe") is not None or s.get("eps") is not None]
        # Retire les points {pe: None, eps: None} → inutiles pour le graphique.
        # Après ce filtre, il reste généralement uniquement le point TTM.

        # ── Étape 4 : Fallback minimal ────────────────────────────────────────
        if not series and (ttm_eps or ttm_pe):
            series = [{"year": "TTM", "pe": ttm_pe, "eps": ttm_eps}]
        # Si le filtre a tout supprimé mais que TTM existe → on le remet.
        # Évite de retourner une liste vide (graphique vide dans le HTML).

        return series

    # ┌─────────────────────────────────────────────────────────────────────────┐
    # │  _fallback_research() — ANALYSE MINIMALE EN CAS D'ÉCHEC               │
    # │  Appelée si le parsing JSON ou la construction Pydantic échoue.        │
    # │  Garantit qu'un titre est toujours dans la liste, même dégradé.       │
    # └─────────────────────────────────────────────────────────────────────────┘

    def _fallback_research(self, idea: Any, error: str) -> ResearchOutput:
        """Retourne une analyse minimale si le parsing echoue."""
        return ResearchOutput(
            ticker = idea.ticker,
            nom    = idea.nom or idea.ticker,

            these_investissement = idea.raison or "Analyse non disponible",
            # On récupère la thèse initiale de IdeaGenerationAgent comme substitute.

            valorisation = {
                "methode_principale":       "N/D",
                "commentaire_valorisation": f"Erreur parsing: {error[:100]}",
                # error[:100] : tronque le message d'erreur (peut être long)
            },

            risques_cles          = ["Donnees insuffisantes"],
            catalyseurs           = [idea.catalyseur or "N/D"],
            score_conviction      = 50,   # Score neutre (ni bon ni mauvais)
            recommandation        = "HOLD",
            # HOLD (pas BUY) → PortfolioConstructionAgent l'ignorera.
            # Raison : sans analyse fiable, mieux vaut ne pas l'inclure.

            poids_suggere_initial = 0.02,
            # Poids minimal de 2% si malgré tout l'agent décide de l'inclure.

            donnees_marche = {},
        )
