"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  TOOLS / SEC EDGAR - RAPPORTS ANNUELS OFFICIELS (10-K)                      ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Rôle : extraire les sections clés du dernier rapport annuel 10-K           ║
║  déposé auprès de la SEC par les sociétés cotées aux USA.                   ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Source  : SEC EDGAR - API publique gratuite, aucune clé requise            ║
║  Limite  : titres US uniquement (NVDA, MSFT, AAPL...).                      ║
║            Les tickers européens (ASML.AS, SIE.DE) retournent SKIP.        ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Sections extraites du 10-K :                                                ║
║    - Item 1A : Risk Factors    (risques officiels déclarés par la société)  ║
║    - Item 7  : MD&A            (analyse de la direction sur les résultats)  ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Flux d'appels :                                                             ║
║    1. company_tickers.json  → ticker → CIK                                  ║
║    2. submissions/{CIK}.json → dernière filing 10-K (accession number)      ║
║    3. Archives/edgar/data/{CIK}/{accession}/ → URL du document principal    ║
║    4. Téléchargement + parsing HTML → extraction Item 1A et Item 7         ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import re
import time
import requests
from bs4 import BeautifulSoup
from typing import Any, Dict, Optional

# ── Configuration HTTP ────────────────────────────────────────────────────────
_HEADERS = {
    "User-Agent": "AlphaSwarm research-tool contact@alphaswarm.local",
    # La SEC impose un User-Agent identifiant l'application.
    # Sans cet en-tête, les requêtes sont bloquées (HTTP 403).
    "Accept-Encoding": "gzip, deflate",
}
_TIMEOUT = 15  # secondes par requête

# ── Cache en mémoire du mapping ticker → CIK ──────────────────────────────────
_TICKER_CIK_CACHE: Dict[str, str] = {}
# Chargé une seule fois depuis SEC puis réutilisé pour tous les tickers du run.
# Évite de retélécharger le fichier company_tickers.json (400 KB) à chaque appel.

# ── Suffixes à nettoyer pour les tickers ─────────────────────────────────────
_EXCHANGE_SUFFIXES = (".AS", ".DE", ".PA", ".L", ".HK", ".T", ".SW", ".MI")
# Les tickers européens/asiatiques ont un suffixe de bourse (ex: "ASML.AS").
# SEC EDGAR ne connaît que le symbole de base (ex: "ASML").
# On tente la recherche sans suffixe, mais si la société n'est pas listée US
# → pas de 10-K → retourne SKIP.


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║  FONCTION PRINCIPALE                                                         ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

def get_sec_annual_report(ticker: str) -> Dict[str, Any]:
    """
    Retourne les sections clés du dernier 10-K pour un ticker US.
    Retourne {"statut": "SKIP"} pour les tickers non-US.
    """

    # ── Étape 1 : Nettoie le ticker (supprime suffixe bourse) ─────────────────
    clean_ticker = ticker.upper()
    for suffix in _EXCHANGE_SUFFIXES:
        if clean_ticker.endswith(suffix.upper()):
            return {"statut": "SKIP", "message": f"Ticker non-US ({ticker})"}

    # ── Étape 2 : Récupère le CIK depuis le mapping SEC ───────────────────────
    cik = _get_cik(clean_ticker)
    if not cik:
        return {"statut": "SKIP", "message": f"CIK introuvable pour {ticker}"}

    # ── Étape 3 : Récupère le dernier 10-K ───────────────────────────────────
    filing = _get_latest_10k(cik)
    if not filing:
        return {"statut": "SKIP", "message": "Aucun 10-K trouvé"}

    # ── Étape 4 : Télécharge et parse le document principal ───────────────────
    doc_url = _get_primary_doc_url(cik, filing["accession"], filing.get("accession_dashed", ""))
    if not doc_url:
        return {"statut": "SKIP", "message": "Document 10-K introuvable"}

    text = _fetch_and_clean(doc_url)
    if not text:
        return {"statut": "SKIP", "message": "Impossible de lire le document"}

    # ── Étape 5 : Extraction des sections clés ────────────────────────────────
    risk_factors = _extract_item(text, [
        r"item\s+1a[\.\s]+risk\s+factors",
        r"risk\s+factors",
    ])

    mda = _extract_item(text, [
        r"item\s+7[\.\s]+management.{0,30}discussion",
        r"management.{0,30}discussion\s+and\s+analysis",
    ])

    return {
        "statut":        "OK",
        "ticker":        ticker,
        "filing_date":   filing.get("date", ""),
        # Date de dépôt du 10-K. Ex: "2024-02-21"
        "risk_factors":  risk_factors,
        # Item 1A : risques déclarés officiellement par la société (2000 chars max)
        "mda":           mda,
        # Item 7 : analyse de la direction (résultats, perspectives) (2000 chars max)
        "source_url":    doc_url,
    }


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║  HELPERS PRIVÉS                                                              ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

def _get_cik(ticker: str) -> Optional[str]:
    """Retourne le CIK (zero-padded à 10 chiffres) depuis le mapping SEC."""
    global _TICKER_CIK_CACHE

    # ── Retour cache si déjà chargé ───────────────────────────────────────────
    if ticker in _TICKER_CIK_CACHE:
        return _TICKER_CIK_CACHE[ticker]

    # ── Chargement du mapping complet ─────────────────────────────────────────
    if not _TICKER_CIK_CACHE:
        try:
            resp = requests.get(
                "https://www.sec.gov/files/company_tickers.json",
                headers=_HEADERS, timeout=_TIMEOUT
            )
            resp.raise_for_status()
            data = resp.json()
            # Format : {0: {"cik_str": "320193", "ticker": "AAPL", "title": "..."}, ...}
            for entry in data.values():
                t = entry.get("ticker", "").upper()
                c = str(entry.get("cik_str", "")).zfill(10)
                # zfill(10) : zero-pad à 10 chiffres → "0000320193"
                # La SEC attend toujours le CIK avec 10 chiffres dans les URLs.
                _TICKER_CIK_CACHE[t] = c
            time.sleep(0.15)
            # Pause de courtoisie : SEC demande max 10 req/s
        except Exception:
            return None

    return _TICKER_CIK_CACHE.get(ticker)


def _get_latest_10k(cik: str) -> Optional[Dict[str, str]]:
    """Retourne l'accession number et la date du dernier 10-K déposé."""
    try:
        url  = f"https://data.sec.gov/submissions/CIK{cik}.json"
        resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        time.sleep(0.15)

        filings = data.get("filings", {}).get("recent", {})
        forms       = filings.get("form",            [])
        accessions  = filings.get("accessionNumber", [])
        dates       = filings.get("filingDate",      [])

        # Cherche le premier (= plus récent) 10-K ou 10-K/A dans la liste
        for form, acc, date in zip(forms, accessions, dates):
            if form in ("10-K", "10-K/A"):
                return {
                    "accession":        acc.replace("-", ""),
                    # Ex: "0001045810-24-000316" → "000104581024000316"
                    # Utilisé pour le chemin du dossier dans l'URL.
                    "accession_dashed": acc,
                    # Ex: "0001045810-24-000316"
                    # Utilisé pour le nom du fichier index : {accession_dashed}-index.json
                    "date": date,
                }
    except Exception:
        pass
    return None


def _get_primary_doc_url(cik: str, accession: str, accession_dashed: str = "") -> Optional[str]:
    """Retourne l'URL du document HTML principal du dépôt 10-K."""
    import re as _re
    try:
        # URL correcte : index.json sans préfixe accession dans le nom de fichier
        # Ex: .../000104581026000021/index.json
        index_url = (
            f"https://www.sec.gov/Archives/edgar/data/"
            f"{int(cik)}/{accession}/index.json"
        )
        resp = requests.get(index_url, headers=_HEADERS, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        time.sleep(0.15)

        base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession}/"
        items = data.get("directory", {}).get("item", [])

        # Filtre : .htm/.html, exclut index et vues XBRL (R\d+.htm)
        candidates = []
        for item in items:
            name = item.get("name", "")
            if not (name.endswith(".htm") or name.endswith(".html")):
                continue
            if "index" in name.lower():
                continue
            if _re.match(r"^R\d+\.htm$", name, _re.IGNORECASE):
                continue
            try:
                size = int(item.get("size", 0) or 0)
            except (ValueError, TypeError):
                size = 0
            candidates.append((size, name))

        if candidates:
            # Le document principal est toujours le plus volumineux
            candidates.sort(reverse=True)
            return base + candidates[0][1]

    except Exception:
        pass
    return None


def _fetch_and_clean(url: str) -> str:
    """Télécharge le document HTML et retourne le texte brut nettoyé."""
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=30)
        # timeout=30 : les 10-K sont volumineux (parfois 5-10 MB)
        resp.raise_for_status()
        time.sleep(0.15)

        soup = BeautifulSoup(resp.content, "html.parser")

        # Supprime les scripts, styles et tableaux (trop bruités)
        for tag in soup(["script", "style", "table"]):
            tag.decompose()

        text = soup.get_text(separator=" ")
        # separator=" " : remplace les balises par des espaces (évite les mots collés)

        text = re.sub(r"\s+", " ", text).strip()
        # Normalise les espaces multiples en un seul espace

        return text

    except Exception:
        return ""


def _extract_item(text: str, patterns: list, max_chars: int = 2000) -> str:
    """
    Extrait une section du 10-K en cherchant un header par regex.
    Retourne les max_chars premiers caractères de la section trouvée.
    """
    text_lower = text.lower()

    for pattern in patterns:
        match = re.search(pattern, text_lower)
        if match:
            start = match.start()
            extract = text[start: start + max_chars].strip()
            # On nettoie les premiers caractères (le header lui-même)
            # en sautant jusqu'au premier point ou retour ligne
            first_break = extract.find(". ", 50)
            if first_break != -1 and first_break < 200:
                extract = extract[first_break + 2:]
            return extract[:max_chars]

    return ""


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║  FORMATAGE POUR LE PROMPT LLM                                               ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

def format_sec_for_prompt(sec_data: Dict[str, Any]) -> str:
    """Formate les données SEC en texte structuré pour le prompt Claude."""

    if sec_data.get("statut") != "OK":
        return ""

    lines = []
    date = sec_data.get("filing_date", "")

    lines.append(f"RAPPORT ANNUEL 10-K (SEC EDGAR - {date}) :")

    risk = sec_data.get("risk_factors", "")
    if risk:
        lines.append("  Facteurs de risque (Item 1A) :")
        lines.append(f"  {risk[:1500]}")
        # Tronqué à 1500 chars : le reste est généralement répétitif

    mda = sec_data.get("mda", "")
    if mda:
        lines.append("  Analyse de la direction (Item 7 - MD&A) :")
        lines.append(f"  {mda[:1500]}")

    return "\n".join(lines)
