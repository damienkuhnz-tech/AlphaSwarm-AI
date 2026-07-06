"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  TOOLS / WEB SEARCH — RECHERCHE WEB VIA TAVILY                              ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Rôle : enrichir l'analyse avec des actualités récentes et les vues         ║
║  d'analystes sell-side non disponibles dans les données historiques.        ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Source  : Tavily AI Search — conçu pour les agents IA                      ║
║  Free tier : 1 000 recherches/mois                                          ║
║  Clé API : settings.TAVILY_API_KEY (depuis .env)                            ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Conception : 2 recherches par ticker                                        ║
║    1. Actualités récentes (résultats, stratégie, produits, régulation)       ║
║    2. Vues analystes (prix cibles, révisions, recommandations)               ║
║  Total : ~20 recherches pour 10 tickers — bien dans le free tier             ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

from typing import Any, Dict, List
from config.settings import settings


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║  GARDE-FOU GLOBAL — clé absente                                             ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

def _key_missing() -> bool:
    """Retourne True si la clé Tavily n'est pas configurée."""
    return not settings.TAVILY_API_KEY or settings.TAVILY_API_KEY == "COLLE_TA_CLÉ_ICI"


def _get_client():
    """Instancie le client Tavily (import lazy pour éviter l'erreur si clé absente)."""
    from tavily import TavilyClient
    return TavilyClient(api_key=settings.TAVILY_API_KEY)


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║  FONCTION PRINCIPALE — RECHERCHE WEB COMPLÈTE POUR UN TICKER               ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

def get_web_research(ticker: str, company_name: str) -> Dict[str, Any]:
    """
    Effectue 2 recherches Tavily et retourne un dict structuré :
      - recent_news    : actualités récentes (résultats, stratégie, risques)
      - analyst_views  : vues analystes (prix cibles, révisions)
    """

    if _key_missing():
        return {"statut": "SKIP", "message": "TAVILY_API_KEY non configurée"}

    try:
        client = _get_client()

        # ── Recherche 1 : Actualités récentes ─────────────────────────────────
        # Requête volontairement large pour capturer : résultats trimestriels,
        # annonces stratégiques, lancements produits, risques réglementaires.
        query_news = f"{company_name} {ticker} latest news earnings results strategy 2025"
        resp_news  = client.search(
            query      = query_news,
            max_results= 5,
            # max_results=5 : bon équilibre qualité/tokens.
            # Tavily retourne des extraits de 200-400 mots par résultat.
        )

        # ── Recherche 2 : Vues analystes ──────────────────────────────────────
        # Cible spécifiquement les rapports d'analystes, prix cibles et révisions.
        query_analysts = f"{company_name} {ticker} analyst price target rating buy sell 2025"
        resp_analysts  = client.search(
            query      = query_analysts,
            max_results= 3,
            # max_results=3 : moins de résultats car les vues analystes sont
            # redondantes entre sources (Reuters, Bloomberg, Seeking Alpha).
        )

        # ── Extraction des résultats ───────────────────────────────────────────
        # Tavily retourne : {"results": [{"title": ..., "content": ..., "url": ...}, ...]}
        news_items     = _extract_results(resp_news)
        analyst_items  = _extract_results(resp_analysts)

        return {
            "statut":        "OK",
            "recent_news":   news_items,
            # Liste de dicts {title, content, url} — actualités récentes
            "analyst_views": analyst_items,
            # Liste de dicts {title, content, url} — vues analystes sell-side
        }

    except Exception as e:
        return {"statut": "ERREUR", "message": str(e)}


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║  COMPOSITION D'UN BENCHMARK — RECHERCHE WEB DES PRINCIPALES PONDÉRATIONS   ║
# ╠═══════════════════════════════════════════════════════════════════════════╣
# ║  Rôle : retrouver via le web les plus grosses composantes d'un indice      ║
# ║  (ex: MSCI World → top holdings). Aucune source gratuite ne donne les       ║
# ║  ~1500 lignes exactes, mais les top pondérations couvrent l'essentiel du    ║
# ║  poids de l'indice et suffisent à constituer un univers benchmark-driven.   ║
# ║                                                                              ║
# ║  Cette fonction ne fait QUE la recherche web : elle retourne le texte brut  ║
# ║  des résultats. L'extraction des tickers (LLM) et leur validation           ║
# ║  (yfinance) sont faites côté agent (séparation des responsabilités).        ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

def get_benchmark_constituents(benchmark_name: str, max_results: int = 5) -> Dict[str, Any]:
    """
    Effectue 1 recherche Tavily sur les principales composantes d'un benchmark.
    Retourne {"statut": "OK"|"SKIP"|"ERREUR", "raw_text": str, "sources": [url, ...]}.
      - SKIP   : clé Tavily absente → l'agent retombera sur son univers par défaut.
      - OK     : raw_text = concaténation titre+contenu des résultats web.
    """

    if not benchmark_name or not benchmark_name.strip():
        return {"statut": "SKIP", "message": "benchmark vide", "raw_text": "", "sources": []}

    if _key_missing():
        return {"statut": "SKIP", "message": "TAVILY_API_KEY non configurée",
                "raw_text": "", "sources": []}

    try:
        client = _get_client()

        # 1 seule recherche (négligeable sur le free tier Tavily 1000/mois).
        # Requête ciblant les pages listant les plus grosses pondérations de l'indice
        # (fiches iShares/SSGA, Wikipédia, Slickcharts, etc.).
        query = (
            f"{benchmark_name} index largest holdings constituents "
            f"top weightings components companies"
        )
        resp  = client.search(query=query, max_results=max_results)

        items = _extract_results(resp)
        if not items:
            return {"statut": "ERREUR", "message": "aucun résultat web",
                    "raw_text": "", "sources": []}

        raw_text = "\n\n".join(f"[{it['title']}]\n{it['content']}" for it in items)
        sources  = [it["url"] for it in items if it.get("url")]

        return {"statut": "OK", "raw_text": raw_text, "sources": sources}

    except Exception as e:
        return {"statut": "ERREUR", "message": str(e), "raw_text": "", "sources": []}


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║  HELPER — EXTRACTION ET NETTOYAGE DES RÉSULTATS TAVILY                     ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

def _extract_results(response: Dict) -> List[Dict[str, str]]:
    """Extrait et nettoie les résultats d'une réponse Tavily."""
    items = []
    for r in response.get("results", []):
        content = r.get("content", "").strip()
        if not content:
            continue
        items.append({
            "title":   r.get("title", ""),
            "content": content[:600],
            # Tronqué à 600 chars : assez pour que Claude comprenne le contexte,
            # pas trop pour ne pas exploser le prompt (5 résultats × 600 = 3000 chars).
            "url":     r.get("url", ""),
        })
    return items


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║  FORMATAGE TEXTE POUR LE PROMPT LLM                                         ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

def format_web_research_for_prompt(web_data: Dict[str, Any]) -> str:
    """
    Convertit le dict web_research en texte structuré pour le prompt Claude.
    Appelée dans _format_market_data() de equity_research_agent.py.
    """

    if web_data.get("statut") != "OK":
        return ""

    lines = []

    # ── Actualités récentes ────────────────────────────────────────────────────
    news = web_data.get("recent_news", [])
    if news:
        lines.append("ACTUALITES RECENTES :")
        for item in news:
            lines.append(f"  [{item['title']}]")
            lines.append(f"  {item['content']}")
            lines.append("")
        # Format : titre entre crochets puis contenu → facile à lire pour Claude

    # ── Vues analystes ─────────────────────────────────────────────────────────
    analysts = web_data.get("analyst_views", [])
    if analysts:
        lines.append("VUES ANALYSTES (sources web) :")
        for item in analysts:
            lines.append(f"  [{item['title']}]")
            lines.append(f"  {item['content']}")
            lines.append("")

    return "\n".join(lines)
