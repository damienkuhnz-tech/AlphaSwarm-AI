"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  TOOLS / REPORT GENERATOR — GÉNÉRATEUR DE RAPPORTS HTML                     ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Rôle : produire des documents HTML autonomes (sans CDN externe) style      ║
║         rapport d'equity research professionnel (FinRobot-inspired).        ║
║  Appelé par : EquityResearchAgent._build_report_data() pour chaque ticker   ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Deux fonctions publiques :                                                 ║
║    generate_company_report(data)  → rapport par entreprise (étape 3/8)     ║
║    generate_sector_report(data)   → rapport sectoriel (non utilisé en V1)  ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Architecture interne :                                                     ║
║    Helpers       : _esc(), _fmt_num(), _fmt_pct(), _rating_color/bg()       ║
║    SVG builders  : _build_price_svg(), _build_pe_eps_svg(),                ║
║                    _build_sector_perf_svg()                                 ║
║    Table builder : _build_financial_table()                                 ║
║    CSS           : _BASE_CSS (inline dans <style>) — aucun CDN nécessaire  ║
║    Assembler     : generate_company_report() / generate_sector_report()     ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Principe "standalone HTML" :                                               ║
║    Tout le CSS est injecté dans <style> dans le <head>.                    ║
║    Tous les graphiques sont des SVG inline (pas d'images externes).        ║
║    → Le fichier .html s'ouvre sans connexion internet.                     ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  IMPORTS                                                                    │
# └─────────────────────────────────────────────────────────────────────────────┘

from typing import Any, Dict, List, Optional
import html as html_lib
# html_lib : module standard Python pour échapper les caractères HTML spéciaux.
# html_lib.escape("<script>") → "&lt;script&gt;"
# Utilisé dans _esc() pour protéger contre l'injection HTML dans les champs LLM.


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║  HELPERS — FONCTIONS UTILITAIRES                                            ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  _esc() — Échappement HTML                                                  │
# └─────────────────────────────────────────────────────────────────────────────┘
# Protège contre les caractères spéciaux HTML dans les chaînes générées par le LLM.
# None → "N/D" (valeur d'affichage standard quand la donnée est absente).

def _esc(val: Any) -> str:
    """Echappe les caracteres HTML."""
    if val is None:
        return "N/D"
    return html_lib.escape(str(val))


# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  _fmt_num() — Formatage numérique                                           │
# └─────────────────────────────────────────────────────────────────────────────┘
# Formate un float avec séparateur de milliers et nombre de décimales configurables.
# suffix : permet d'ajouter "%" après le nombre (mais _fmt_pct est plus lisible pour ça).
# try/except : le LLM peut renvoyer des strings là où on attend des floats.

def _fmt_num(val: Any, decimals: int = 2, suffix: str = "") -> str:
    """Formate un nombre avec separateur de milliers."""
    if val is None:
        return "N/D"
    try:
        return f"{float(val):,.{decimals}f}{suffix}"
        # f"{1234567.89:,.2f}" → "1,234,567.89"
    except (ValueError, TypeError):
        return str(val)
        # Fallback : retourne la valeur telle quelle si elle n'est pas convertible


# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  _fmt_pct() — Formatage pourcentage                                         │
# └─────────────────────────────────────────────────────────────────────────────┘
# Convertit un ratio décimal (0.15) en pourcentage affiché ("15.0%").
# Note : multiplie par 100 → les valeurs en entrée sont des fractions (0 à 1).

def _fmt_pct(val: Any) -> str:
    """Formate un ratio en pourcentage."""
    if val is None:
        return "N/D"
    try:
        return f"{float(val) * 100:.1f}%"
    except (ValueError, TypeError):
        return str(val)


# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  _rating_color() / _rating_bg() — Couleurs selon la recommandation         │
# └─────────────────────────────────────────────────────────────────────────────┘
# Mapping recommendation → couleurs de badge HTML.
# Palette choisie pour lisibilité financière (vert foncé = fort buy, rouge = sell).
# default : #333333 (gris neutre) si la valeur ne correspond à aucun rating connu.

def _rating_color(rating: str) -> str:
    # Couleur de texte du badge recommendation
    mapping = {
        "strongBuy": "#1b5e20",   # Vert très foncé
        "Buy":       "#2e7d32",   # Vert foncé
        "Hold":      "#e65100",   # Orange
        "Sell":      "#b71c1c",   # Rouge foncé
    }
    return mapping.get(rating, "#333333")


def _rating_bg(rating: str) -> str:
    # Couleur de fond du badge recommendation (pastel assorti au texte)
    mapping = {
        "strongBuy": "#e8f5e9",   # Vert très pâle
        "Buy":       "#f1f8e9",   # Vert pâle
        "Hold":      "#fff3e0",   # Orange pâle
        "Sell":      "#ffebee",   # Rouge pâle
    }
    return mapping.get(rating, "#f5f5f5")


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║  SVG BUILDERS — GRAPHIQUES INLINE                                           ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  _build_price_svg() — Graphique Share Performance vs S&P 500               │
# └─────────────────────────────────────────────────────────────────────────────┘
# Produit un SVG ligne avec 2 courbes :
#   - Ligne bleue (#1565c0)  : performance du ticker (base 100)
#   - Ligne grise pointillée : performance S&P 500 (base 100)
# Les données viennent de get_price_series() dans tools/market_data.py.
# "base 100" signifie : le premier point est normalisé à 100, les suivants
# reflètent la variation en % relative au premier jour.
# W, H : dimensions du SVG en pixels (400×180, compact pour sidebar).
# PAD_L/R/T/B : marges pour les axes et légendes.

def _build_price_svg(ticker: str, series: List[Dict]) -> str:
    """Genere un SVG ligne pour Share Performance vs benchmark."""

    # ── BLOC 1 : Dimensions et marges ─────────────────────────────────────────
    W, H = 400, 180
    # PAD_L=45 : marge gauche pour labels axe Y (ex: "85", "100", "115")
    # PAD_B=40 : marge bas pour labels axe X (dates) + légende
    PAD_L, PAD_R, PAD_T, PAD_B = 45, 15, 20, 40

    # ── BLOC 2 : Fallback si données vides ────────────────────────────────────
    if not series:
        # SVG minimal avec message centré — n'interrompt pas le rendu du rapport
        return f'<svg width="{W}" height="{H}"><text x="50%" y="50%" text-anchor="middle" fill="#999">Donnees indisponibles</text></svg>'

    # ── BLOC 3 : Extraction des valeurs ───────────────────────────────────────
    t_vals = [p.get("ticker_val", 100) for p in series]
    # ticker_val : valeur normalisée base 100 du titre
    b_vals = [p.get("benchmark_val", 100) for p in series]
    # benchmark_val : valeur normalisée base 100 du benchmark (S&P 500 ^GSPC)
    all_vals = t_vals + b_vals
    # Calcul du range Y avec 3% de marge de chaque côté pour aérer le graphique
    y_min = min(all_vals) * 0.97
    y_max = max(all_vals) * 1.03
    dates = [p.get("date", "") for p in series]
    n = len(series)

    # ── BLOC 4 : Espace de dessin ─────────────────────────────────────────────
    chart_w = W - PAD_L - PAD_R   # Largeur utile de la zone de dessin
    chart_h = H - PAD_T - PAD_B   # Hauteur utile de la zone de dessin

    # ── BLOC 5 : Fonctions de projection coordonnées → pixels ─────────────────
    def x_px(i: int) -> float:
        # i = index du point (0 à n-1) → coordonnée X en pixels
        # max(n-1, 1) : évite division par zéro si un seul point
        return PAD_L + (i / max(n - 1, 1)) * chart_w

    def y_px(v: float) -> float:
        # v = valeur (ex: 105.3) → coordonnée Y en pixels
        # L'axe Y est inversé en SVG (0 = haut), donc on fait (1 - ...)
        # max(y_max - y_min, 1) : évite division par zéro si toutes valeurs identiques
        return PAD_T + (1 - (v - y_min) / max(y_max - y_min, 1)) * chart_h

    # ── BLOC 6 : Construction des polylines ───────────────────────────────────
    # SVG polyline : liste de "x,y" séparés par des espaces
    # Ex: "45.0,120.5 67.2,110.3 89.4,95.7"
    t_points = " ".join(f"{x_px(i):.1f},{y_px(v):.1f}" for i, v in enumerate(t_vals))
    b_points = " ".join(f"{x_px(i):.1f},{y_px(v):.1f}" for i, v in enumerate(b_vals))

    # ── BLOC 7 : Labels axe Y (3 niveaux) ────────────────────────────────────
    y_levels = [y_min, (y_min + y_max) / 2, y_max]
    y_labels = "".join(
        f'<text x="{PAD_L - 5}" y="{y_px(v) + 4:.1f}" text-anchor="end" font-size="9" fill="#666">{v:.0f}</text>'
        for v in y_levels
    )

    # ── BLOC 8 : Labels axe X (3 dates espacées régulièrement) ───────────────
    x_idx = [0, n // 2, n - 1]
    # 3 dates : début, milieu, fin — évite le chevauchement de texte
    x_labels = "".join(
        f'<text x="{x_px(i):.1f}" y="{H - PAD_B + 14}" text-anchor="middle" font-size="9" fill="#666">{_esc(dates[i])}</text>'
        for i in x_idx if i < n
    )

    # ── BLOC 9 : Légende ──────────────────────────────────────────────────────
    legend = (
        f'<rect x="{PAD_L}" y="{H - PAD_B + 22}" width="10" height="3" fill="#1565c0"/>'
        # Petit rectangle bleu pour le ticker
        f'<text x="{PAD_L + 14}" y="{H - PAD_B + 27}" font-size="9" fill="#333">{_esc(ticker)}</text>'
        f'<rect x="{PAD_L + 60}" y="{H - PAD_B + 22}" width="10" height="3" fill="#9e9e9e" stroke-dasharray="3,2"/>'
        # Petit rectangle gris pointillé pour le benchmark
        f'<text x="{PAD_L + 74}" y="{H - PAD_B + 27}" font-size="9" fill="#333">S&amp;P 500</text>'
        # &amp; : entité HTML pour "&" (nécessaire dans les attributs SVG)
    )

    # ── BLOC 10 : Assemblage SVG final ────────────────────────────────────────
    svg = f"""<svg width="{W}" height="{H}" xmlns="http://www.w3.org/2000/svg">
  <rect width="{W}" height="{H}" fill="white"/>
  <!-- Grille -->
  <line x1="{PAD_L}" y1="{PAD_T}" x2="{PAD_L}" y2="{PAD_T + chart_h}" stroke="#e0e0e0" stroke-width="1"/>
  <line x1="{PAD_L}" y1="{PAD_T + chart_h}" x2="{PAD_L + chart_w}" y2="{PAD_T + chart_h}" stroke="#e0e0e0" stroke-width="1"/>
  <!-- Benchmark (pointille gris) -->
  <polyline points="{b_points}" fill="none" stroke="#9e9e9e" stroke-width="1.5" stroke-dasharray="4,3"/>
  <!-- Ticker (ligne bleue) -->
  <polyline points="{t_points}" fill="none" stroke="#1565c0" stroke-width="2"/>
  {y_labels}
  {x_labels}
  {legend}
</svg>"""
    return svg


# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  _build_pe_eps_svg() — Graphique PE Ratio + EPS historiques                │
# └─────────────────────────────────────────────────────────────────────────────┘
# Double axe Y :
#   - Axe gauche (bleu)  : PE Ratio (ligne + points circulaires)
#   - Axe droit (gris)   : EPS (barres)
# Données : 4 dernières années fiscales (series[].year, .pe, .eps).
# PAD_R=45 : plus large que les autres SVGs car axe droit a besoin d'espace.

def _build_pe_eps_svg(company_name: str, series: List[Dict]) -> str:
    """Genere un SVG barres EPS + ligne PE avec double axe."""

    # ── BLOC 1 : Dimensions ───────────────────────────────────────────────────
    W, H = 400, 180
    PAD_L, PAD_R, PAD_T, PAD_B = 45, 45, 20, 40
    # PAD_R=45 : nécessaire pour afficher les labels de l'axe droit (EPS)

    # ── BLOC 2 : Fallback si données vides ────────────────────────────────────
    if not series:
        return f'<svg width="{W}" height="{H}"><text x="50%" y="50%" text-anchor="middle" fill="#999">Donnees indisponibles</text></svg>'

    # ── BLOC 3 : Extraction et normalisation des valeurs ──────────────────────
    pe_vals  = [float(p.get("pe", 0) or 0) for p in series]
    # "or 0" : None ou 0 deviennent 0 (évite l'erreur float(None))
    eps_vals = [float(p.get("eps", 0) or 0) for p in series]
    years    = [str(p.get("year", "")) for p in series]
    n = len(series)

    # ── BLOC 4 : Espace de dessin ─────────────────────────────────────────────
    chart_w = W - PAD_L - PAD_R
    chart_h = H - PAD_T - PAD_B

    # ── BLOC 5 : Ranges pour les deux axes Y ──────────────────────────────────
    eps_min = 0           # L'axe EPS commence à 0 (pas de négatifs affichés)
    eps_max = max(max(eps_vals) * 1.2, 1)
    # 1.2 : marge de 20% au-dessus du max pour aérer; max(...,1) : évite max=0

    pe_min = 0
    pe_max = max(max(pe_vals) * 1.2, 10)
    # max(...,10) : PE minimum de 10x pour éviter une échelle trop compressée

    # ── BLOC 6 : Largeur et espacement des barres ─────────────────────────────
    bar_w = max(chart_w / n * 0.5, 5)
    # 50% de l'espace par barre → gap entre barres = 50% de l'espace
    # max(...,5) : barre d'au moins 5px de large quelle que soit la résolution
    bar_gap = chart_w / n

    # ── BLOC 7 : Fonctions de projection ──────────────────────────────────────
    def x_center(i: int) -> float:
        # Centre de la barre i (pour placer à la fois la barre et le point PE)
        return PAD_L + (i + 0.5) * bar_gap

    def y_eps(v: float) -> float:
        # Axe droit : EPS. Même logique Y inversée que _build_price_svg()
        return PAD_T + (1 - (v - eps_min) / max(eps_max - eps_min, 1)) * chart_h

    def y_pe(v: float) -> float:
        # Axe gauche : PE Ratio. Indépendant de l'axe EPS → double axe
        return PAD_T + (1 - (v - pe_min) / max(pe_max - pe_min, 1)) * chart_h

    # ── BLOC 8 : Construction des barres EPS ──────────────────────────────────
    bars = ""
    for i, v in enumerate(eps_vals):
        bx = x_center(i) - bar_w / 2   # Coin gauche de la barre
        by = y_eps(v)                    # Sommet de la barre
        bh = PAD_T + chart_h - by       # Hauteur = distance entre sommet et axe X
        bars += f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bar_w:.1f}" height="{bh:.1f}" fill="#bdbdbd" opacity="0.8"/>'
        # Barres grises (#bdbdbd) semi-transparentes pour ne pas masquer la ligne PE

    # ── BLOC 9 : Ligne PE + points circulaires ────────────────────────────────
    pe_pts  = " ".join(f"{x_center(i):.1f},{y_pe(v):.1f}" for i, v in enumerate(pe_vals))
    pe_line = f'<polyline points="{pe_pts}" fill="none" stroke="#1565c0" stroke-width="2"/>'
    pe_dots = "".join(
        f'<circle cx="{x_center(i):.1f}" cy="{y_pe(v):.1f}" r="3" fill="#1565c0"/>'
        # Cercles bleus r=3 pour marquer chaque point de données sur la ligne PE
        for i, v in enumerate(pe_vals)
    )

    # ── BLOC 10 : Labels axe X (années) ──────────────────────────────────────
    x_labels = "".join(
        f'<text x="{x_center(i):.1f}" y="{PAD_T + chart_h + 14}" text-anchor="middle" font-size="9" fill="#666">{_esc(years[i])}</text>'
        for i in range(n)
    )

    # ── BLOC 11 : Labels axe Y gauche (PE) ───────────────────────────────────
    pe_levels = [pe_min, pe_max / 2, pe_max]
    y_left = "".join(
        f'<text x="{PAD_L - 5}" y="{y_pe(v) + 4:.1f}" text-anchor="end" font-size="9" fill="#1565c0">{v:.0f}</text>'
        # Texte bleu pour l'axe PE (couleur assortie à la ligne)
        for v in pe_levels
    )

    # ── BLOC 12 : Labels axe Y droit (EPS) ───────────────────────────────────
    eps_levels = [eps_min, eps_max / 2, eps_max]
    y_right = "".join(
        f'<text x="{W - PAD_R + 5}" y="{y_eps(v) + 4:.1f}" text-anchor="start" font-size="9" fill="#555">{v:.1f}</text>'
        # Texte gris à droite du graphique pour l'axe EPS
        for v in eps_levels
    )

    # ── BLOC 13 : Légende ─────────────────────────────────────────────────────
    legend = (
        f'<line x1="{PAD_L}" y1="{H - PAD_B + 22}" x2="{PAD_L + 14}" y2="{H - PAD_B + 22}" stroke="#1565c0" stroke-width="2"/>'
        f'<text x="{PAD_L + 18}" y="{H - PAD_B + 27}" font-size="9" fill="#333">PE Ratio (gauche)</text>'
        f'<rect x="{PAD_L + 120}" y="{H - PAD_B + 18}" width="10" height="8" fill="#bdbdbd" opacity="0.8"/>'
        f'<text x="{PAD_L + 134}" y="{H - PAD_B + 27}" font-size="9" fill="#333">EPS (droite)</text>'
    )

    # ── BLOC 14 : Assemblage SVG final ────────────────────────────────────────
    svg = f"""<svg width="{W}" height="{H}" xmlns="http://www.w3.org/2000/svg">
  <rect width="{W}" height="{H}" fill="white"/>
  <line x1="{PAD_L}" y1="{PAD_T}" x2="{PAD_L}" y2="{PAD_T + chart_h}" stroke="#e0e0e0" stroke-width="1"/>
  <line x1="{PAD_L}" y1="{PAD_T + chart_h}" x2="{PAD_L + chart_w}" y2="{PAD_T + chart_h}" stroke="#e0e0e0" stroke-width="1"/>
  {bars}
  {pe_line}
  {pe_dots}
  {x_labels}
  {y_left}
  {y_right}
  {legend}
</svg>"""
    return svg


# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  _build_sector_perf_svg() — Performance sectorielle vs benchmark           │
# └─────────────────────────────────────────────────────────────────────────────┘
# Utilisé exclusivement par generate_sector_report() (rapport sectoriel).
# Non utilisé en V1 de production (generate_company_report est appelé par EquityResearchAgent).
# Même logique que _build_price_svg() mais avec la couleur mauve (#7b1fa2)
# pour distinguer visuellement les rapports sectoriels des rapports entreprise.

def _build_sector_perf_svg(sector_series: List[Dict]) -> str:
    """SVG pour performance sectorielle vs benchmark."""

    # ── BLOC 1 : Dimensions ───────────────────────────────────────────────────
    W, H = 400, 180
    PAD_L, PAD_R, PAD_T, PAD_B = 45, 15, 20, 40

    # ── BLOC 2 : Fallback ─────────────────────────────────────────────────────
    if not sector_series:
        return f'<svg width="{W}" height="{H}"><text x="50%" y="50%" text-anchor="middle" fill="#999">Donnees indisponibles</text></svg>'

    # ── BLOC 3 : Extraction ───────────────────────────────────────────────────
    s_vals = [float(p.get("sector_val", 100)) for p in sector_series]
    # sector_val : performance sectorielle normalisée base 100
    b_vals = [float(p.get("benchmark_val", 100)) for p in sector_series]
    all_vals = s_vals + b_vals
    y_min = min(all_vals) * 0.97
    y_max = max(all_vals) * 1.03
    dates = [p.get("date", "") for p in sector_series]
    n = len(sector_series)

    # ── BLOC 4 : Espace de dessin + projections ───────────────────────────────
    chart_w = W - PAD_L - PAD_R
    chart_h = H - PAD_T - PAD_B

    def x_px(i: int) -> float:
        return PAD_L + (i / max(n - 1, 1)) * chart_w

    def y_px(v: float) -> float:
        return PAD_T + (1 - (v - y_min) / max(y_max - y_min, 1)) * chart_h

    # ── BLOC 5 : Polylines ────────────────────────────────────────────────────
    s_pts = " ".join(f"{x_px(i):.1f},{y_px(v):.1f}" for i, v in enumerate(s_vals))
    b_pts = " ".join(f"{x_px(i):.1f},{y_px(v):.1f}" for i, v in enumerate(b_vals))

    # ── BLOC 6 : Labels axe Y ─────────────────────────────────────────────────
    y_levels = [y_min, (y_min + y_max) / 2, y_max]
    y_labels = "".join(
        f'<text x="{PAD_L - 5}" y="{y_px(v) + 4:.1f}" text-anchor="end" font-size="9" fill="#666">{v:.0f}</text>'
        for v in y_levels
    )

    # ── BLOC 7 : Labels axe X ─────────────────────────────────────────────────
    x_idx = [0, n // 2, n - 1]
    x_labels = "".join(
        f'<text x="{x_px(i):.1f}" y="{H - PAD_B + 14}" text-anchor="middle" font-size="9" fill="#666">{_esc(dates[i])}</text>'
        for i in x_idx if i < n
    )

    # ── BLOC 8 : Légende ──────────────────────────────────────────────────────
    legend = (
        f'<rect x="{PAD_L}" y="{H - PAD_B + 22}" width="10" height="3" fill="#7b1fa2"/>'
        # Mauve (#7b1fa2) : couleur sectorielle, distinct du bleu entreprise
        f'<text x="{PAD_L + 14}" y="{H - PAD_B + 27}" font-size="9" fill="#333">Secteur</text>'
        f'<rect x="{PAD_L + 70}" y="{H - PAD_B + 22}" width="10" height="3" fill="#9e9e9e"/>'
        f'<text x="{PAD_L + 84}" y="{H - PAD_B + 27}" font-size="9" fill="#333">Benchmark</text>'
    )

    # ── BLOC 9 : Assemblage SVG ───────────────────────────────────────────────
    return f"""<svg width="{W}" height="{H}" xmlns="http://www.w3.org/2000/svg">
  <rect width="{W}" height="{H}" fill="white"/>
  <line x1="{PAD_L}" y1="{PAD_T}" x2="{PAD_L}" y2="{PAD_T + chart_h}" stroke="#e0e0e0" stroke-width="1"/>
  <line x1="{PAD_L}" y1="{PAD_T + chart_h}" x2="{PAD_L + chart_w}" y2="{PAD_T + chart_h}" stroke="#e0e0e0" stroke-width="1"/>
  <polyline points="{b_pts}" fill="none" stroke="#9e9e9e" stroke-width="1.5" stroke-dasharray="4,3"/>
  <polyline points="{s_pts}" fill="none" stroke="#7b1fa2" stroke-width="2"/>
  {y_labels}
  {x_labels}
  {legend}
</svg>"""


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║  TABLE BUILDER — TABLEAU FINANCIER                                          ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  _build_financial_table() — Tableau HTML des métriques financières         │
# └─────────────────────────────────────────────────────────────────────────────┘
# Construit un tableau HTML multi-colonnes avec une année par colonne.
# Lignes : Revenue, Net Income, EPS, EBIT Margin, ROE, PE, EV/EBITDA, PB.
# row() closure : génère une ligne <tr> avec les cellules formatées.
# Alternance de fond (i%2 : #f9f9f9 / #ffffff) pour lisibilité (zebrastripes).

def _build_financial_table(metrics: List[Dict]) -> str:
    """Construit le tableau HTML des metriques financieres historiques."""

    # ── BLOC 1 : Fallback si pas de données ───────────────────────────────────
    if not metrics:
        return "<p><em>Donnees financieres non disponibles.</em></p>"

    # ── BLOC 2 : En-têtes des colonnes (années) ───────────────────────────────
    years = [m.get("year", "") for m in metrics]
    header_years = "".join(f"<th>{_esc(y)}</th>" for y in years)

    # ── BLOC 3 : Closure row() pour construire chaque ligne ───────────────────
    def row(label: str, key: str, fmt_fn=None) -> str:
        # label : nom de la métrique affiché à gauche (ex: "Operating Revenue")
        # key   : clé dans le dict metrics[i] (ex: "revenue")
        # fmt_fn : fonction de formatage optionnelle (ex: _fmt_pct pour les marges)
        cells = ""
        for i, m in enumerate(metrics):
            val = m.get(key)
            if fmt_fn:
                display = fmt_fn(val)
            else:
                display = _fmt_num(val, 0) if val is not None else "N/D"
            bg = "#f9f9f9" if i % 2 == 0 else "#ffffff"
            # Alternance de fond par colonne (pas par ligne) pour lire horizontalement
            cells += f'<td style="background:{bg};text-align:right;padding:5px 8px;">{display}</td>'
        return f"<tr><td style='padding:5px 8px;font-weight:500;color:#333;'>{label}</td>{cells}</tr>"

    # ── BLOC 4 : Construction des lignes du tableau ────────────────────────────
    rows = (
        row("Operating Revenue (USD mn)", "revenue",     lambda v: _fmt_num(v, 0))
        + row("Net Income (USD mn)",      "net_income",  lambda v: _fmt_num(v, 0))
        + row("EPS (USD)",                "eps",         lambda v: _fmt_num(v, 2))
        + row("EBIT Margin",              "ebit_margin", lambda v: _fmt_pct(v))
        + row("ROE",                      "roe",         lambda v: _fmt_pct(v))
        + row("PE Ratio",                 "pe_ratio",    lambda v: _fmt_num(v, 1))
        + row("EV/EBITDA",                "ev_ebitda",   lambda v: _fmt_num(v, 1))
        + row("PB Ratio",                 "pb_ratio",    lambda v: _fmt_num(v, 1))
    )

    # ── BLOC 5 : Assemblage HTML ───────────────────────────────────────────────
    return f"""
<table style="width:100%;border-collapse:collapse;font-size:13px;margin-top:10px;">
  <thead>
    <tr style="background:#1a237e;color:white;">
      <th style="padding:7px 8px;text-align:left;">FY (USD mn)</th>
      {header_years}
    </tr>
  </thead>
  <tbody>
    {rows}
  </tbody>
</table>"""


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║  CSS COMMUN — STYLES INLINE (PAS DE CDN)                                   ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  _BASE_CSS — Feuille de style commune aux deux types de rapports           │
# └─────────────────────────────────────────────────────────────────────────────┘
# Injecté dans <style> dans le <head> de chaque rapport HTML.
# Conception : layout 2 colonnes (70% contenu / 30% sidebar) via CSS flexbox.
# Couleur principale : #1a237e (bleu navy institutionnel).
# Aucun CDN : tout est auto-contenu dans le fichier HTML pour usage offline.
# Classes principales :
#   .report-wrapper    : conteneur centré max 1100px avec ombre
#   .report-header     : bande supérieure avec titre + logo AlphaSwarm
#   .report-body       : zone flex 2 colonnes
#   .col-left (70%)    : sections narratives + tableau financier
#   .col-right (30%)   : sidebar Key Data + graphiques SVG
#   .sidebar-card      : carte de données avec bordure gauche bleue (4px)
#   .key-data-row      : ligne label/valeur dans la sidebar
#   .rating-badge      : badge coloré pour la recommandation (Buy/Hold/Sell)
#   .chart-title       : titre centré au-dessus de chaque SVG
#   .report-footer     : pied de page avec disclaimer légal

_BASE_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: Arial, sans-serif;
    font-size: 13px;
    color: #333;
    background: #f0f0f0;
    padding: 20px;
}
.report-wrapper {
    max-width: 1100px;
    margin: 0 auto;
    background: #fff;
    box-shadow: 0 2px 8px rgba(0,0,0,0.15);
}
/* Header */
.report-header {
    background: #fff;
    border-bottom: 3px solid #1a237e;
    padding: 18px 24px 14px;
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
}
.report-header-left h1 {
    font-size: 20px;
    color: #1a237e;
    font-weight: 700;
    margin-bottom: 4px;
}
.report-header-left .subtitle {
    font-size: 12px;
    color: #555;
}
.report-header-right {
    text-align: right;
}
.logo-text {
    font-size: 18px;
    font-weight: 700;
    color: #1a237e;
    letter-spacing: 1px;
}
.report-date {
    font-size: 11px;
    color: #777;
    margin-top: 4px;
}
/* Layout 2 colonnes */
.report-body {
    display: flex;
    gap: 0;
}
.col-left {
    flex: 0 0 70%;
    padding: 20px 24px;
    border-right: 1px solid #e0e0e0;
}
.col-right {
    flex: 0 0 30%;
    padding: 16px;
    background: #fafafa;
}
/* Sections narratives */
.section {
    margin-bottom: 22px;
}
.section h2 {
    font-size: 14px;
    font-weight: 700;
    color: #1a237e;
    border-bottom: 2px solid #e3e8f0;
    padding-bottom: 5px;
    margin-bottom: 9px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}
.section p {
    line-height: 1.65;
    color: #333;
    font-size: 13px;
}
/* Sidebar cards */
.sidebar-card {
    background: #fff;
    border: 1px solid #e0e0e0;
    border-left: 4px solid #1a237e;
    border-radius: 3px;
    padding: 12px;
    margin-bottom: 16px;
}
.sidebar-card h3 {
    font-size: 12px;
    font-weight: 700;
    text-transform: uppercase;
    color: #1a237e;
    letter-spacing: 0.5px;
    margin-bottom: 10px;
    border-bottom: 1px solid #e8eaf6;
    padding-bottom: 5px;
}
.key-data-row {
    display: flex;
    justify-content: space-between;
    padding: 4px 0;
    border-bottom: 1px dotted #eeeeee;
    font-size: 12px;
}
.key-data-row:last-child {
    border-bottom: none;
}
.key-data-label {
    color: #555;
}
.key-data-value {
    font-weight: 600;
    color: #222;
}
.rating-badge {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 3px;
    font-weight: 700;
    font-size: 12px;
}
.chart-title {
    font-size: 11px;
    font-weight: 600;
    color: #444;
    margin-bottom: 6px;
    text-align: center;
}
/* Footer */
.report-footer {
    border-top: 2px solid #e0e0e0;
    padding: 12px 24px;
    font-size: 11px;
    color: #777;
    text-align: center;
    background: #fafafa;
}
"""


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║  FONCTION PUBLIQUE 1 : generate_company_report()                           ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  generate_company_report() — Rapport HTML par entreprise                   │
# └─────────────────────────────────────────────────────────────────────────────┘
# Appelé par EquityResearchAgent._build_report_data() → generate_company_report(data).
# Le dict "data" est construit par _build_report_data() dans equity_research_agent.py.
# Structure du dict attendu :
#   ticker, company_name, report_date, source        → Header
#   income_summary, business_highlights,             → Colonne gauche (texte LLM)
#   company_situation, risk_assessment
#   rating, target_price_low/high, avg_daily_vol,    → Sidebar Key Data
#   closing_price, market_cap, week_52_low/high,
#   bvps, pe_ratio, eps_ttm
#   price_series    → List[{date, ticker_val, benchmark_val}] → SVG courbe
#   pe_eps_series   → List[{year, pe, eps}] → SVG barres/ligne
#   financial_metrics → List[{year, revenue, net_income, eps, ...}] → Tableau

def generate_company_report(data: dict) -> str:
    """
    Genere un rapport HTML complet d'equity research pour une entreprise.

    Parametres
    ----------
    data : dict
        Voir la specification dans le module (ticker, company_name, sections
        narratives, sidebar Key Data, financial_metrics, price_series,
        pe_eps_series).

    Retour
    ------
    str : document HTML autonome complet.
    """

    # ── BLOC 1 : Extraction des métadonnées ───────────────────────────────────
    ticker       = data.get("ticker", "N/D")
    company_name = data.get("company_name", ticker)
    report_date  = data.get("report_date", "N/D")
    source       = data.get("source", "AlphaSwarm Research")
    # source : affiché dans le sous-titre du header ("7203.T | AlphaSwarm Research")

    # ── BLOC 2 : Sections narratives (générées par le LLM) ────────────────────
    executive_summary   = data.get("executive_summary", "")
    income_summary      = data.get("income_summary", "")
    business_highlights = data.get("business_highlights", "")
    company_situation   = data.get("company_situation", "")
    risk_assessment     = data.get("risk_assessment", "")
    # Ces 4 sections sont du texte libre écrit par Claude dans REPORT_NARRATIVE_PROMPT.
    # Chaque section correspond à une h2 dans la colonne gauche.

    # ── BLOC 3 : Données sidebar Key Data ─────────────────────────────────────
    rating    = data.get("rating", "Hold")
    # rating : "strongBuy" | "Buy" | "Hold" | "Sell" (vient de yfinance info)
    target_low  = data.get("target_price_low")
    target_high = data.get("target_price_high")
    avg_vol     = data.get("avg_daily_vol")
    closing     = data.get("closing_price")
    mktcap      = data.get("market_cap")
    w52_low     = data.get("week_52_low")
    w52_high    = data.get("week_52_high")
    bvps        = data.get("bvps")        # Book Value Per Share
    pe_ratio    = data.get("pe_ratio")
    eps_ttm     = data.get("eps_ttm")     # Earnings Per Share (Trailing Twelve Months)

    # ── BLOC 4 : Données graphiques ───────────────────────────────────────────
    price_series     = data.get("price_series", [])
    # List[{date, ticker_val, benchmark_val}] — vient de get_price_series()
    pe_eps_series    = data.get("pe_eps_series", [])
    # List[{year, pe, eps}] — vient de _build_pe_eps_series()
    financial_metrics = data.get("financial_metrics", [])
    # List[{year, revenue, net_income, eps, ebit_margin, roe, pe_ratio, ev_ebitda, pb_ratio}]
    # vient de _build_financial_metrics() dans equity_research_agent.py

    # ── BLOC 5 : Construction du badge rating ─────────────────────────────────
    r_color = _rating_color(rating)
    r_bg    = _rating_bg(rating)
    rating_badge = (
        f'<span class="rating-badge" style="color:{r_color};background:{r_bg};'
        f'border:1px solid {r_color};">{_esc(rating)}</span>'
        # Badge inline-block avec couleur de texte + fond + bordure assortis
    )

    # ── BLOC 6 : Génération des SVGs ──────────────────────────────────────────
    price_svg  = _build_price_svg(ticker, price_series)
    pe_eps_svg = _build_pe_eps_svg(company_name, pe_eps_series)

    # ── BLOC 7 : Génération du tableau financier ───────────────────────────────
    fin_table = _build_financial_table(financial_metrics)

    # ── BLOC 8 : Formatage du target price ────────────────────────────────────
    # Affiche "85 – 120" si les deux bornes sont connues, sinon une seule borne.
    if target_low and target_high:
        target_display = f"{_fmt_num(target_low, 0)} – {_fmt_num(target_high, 0)}"
    elif target_low:
        target_display = _fmt_num(target_low, 0)
    elif target_high:
        target_display = _fmt_num(target_high, 0)
    else:
        target_display = "N/D"

    # ── BLOC 9 : Formatage du range 52 semaines ───────────────────────────────
    if w52_low and w52_high:
        w52_display = f"{_fmt_num(w52_low, 2)} – {_fmt_num(w52_high, 2)}"
    else:
        w52_display = "N/D"

    # ── BLOC 10a : Executive Summary HTML (construit avant la f-string) ─────────
    if executive_summary:
        exec_summary_html = (
            '<div class="section" style="background:#f0f4ff;border-left:4px solid #1a237e;'
            'padding:16px 20px;margin-bottom:18px;">'
            '<h2 style="margin-top:0;font-size:13px;text-transform:uppercase;'
            'letter-spacing:.08em;color:#1a237e;">Executive Summary</h2>'
            f'<p style="white-space:pre-line;font-size:13px;line-height:1.7;">{_esc(executive_summary)}</p>'
            '</div>'
        )
    else:
        exec_summary_html = ""

    # ── BLOC 10 : Assemblage HTML complet ─────────────────────────────────────
    # Structure globale : <!DOCTYPE html> → <head> (CSS) → <body>
    #   .report-wrapper
    #     .report-header (titre + logo)
    #     .report-body (flex)
    #       .col-left (sections narratives + tableau)
    #       .col-right (Key Data sidebar + graphiques)
    #     .report-footer (disclaimer)
    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Equity Research — {_esc(company_name)} ({_esc(ticker)})</title>
<style>
{_BASE_CSS}
</style>
</head>
<body>
<div class="report-wrapper">

  <!-- HEADER -->
  <div class="report-header">
    <div class="report-header-left">
      <h1>Equity Research Report: {_esc(company_name)}</h1>
      <div class="subtitle">{_esc(ticker)} &nbsp;|&nbsp; {_esc(source)}</div>
    </div>
    <div class="report-header-right">
      <div class="logo-text">AlphaSwarm</div>
      <div style="font-size:11px;color:#1a237e;font-weight:600;">alphaswarm.ai</div>
      <div class="report-date">Report date: {_esc(report_date)}</div>
    </div>
  </div>

  <!-- BODY 2 colonnes -->
  <div class="report-body">

    <!-- COLONNE GAUCHE (70%) : contenu narratif + tableau financier -->
    <div class="col-left">

      {exec_summary_html}

      <div class="section">
        <h2>Income Summarization</h2>
        <p>{_esc(income_summary) if income_summary else "<em>Section non disponible.</em>"}</p>
      </div>

      <div class="section">
        <h2>Business Highlights</h2>
        <p>{_esc(business_highlights) if business_highlights else "<em>Section non disponible.</em>"}</p>
      </div>

      <div class="section">
        <h2>Company Situation</h2>
        <p>{_esc(company_situation) if company_situation else "<em>Section non disponible.</em>"}</p>
      </div>

      <div class="section">
        <h2>Risk Assessment</h2>
        <p>{_esc(risk_assessment) if risk_assessment else "<em>Section non disponible.</em>"}</p>
      </div>

      <div class="section">
        <h2>Financial Metrics</h2>
        {fin_table}
      </div>

    </div>

    <!-- COLONNE DROITE (30%) : sidebar Key Data + graphiques SVG -->
    <div class="col-right">

      <!-- Key Data : résumé des métriques boursières -->
      <div class="sidebar-card">
        <h3>Key Data</h3>
        <div class="key-data-row">
          <span class="key-data-label">Rating</span>
          <span class="key-data-value">{rating_badge}</span>
        </div>
        <div class="key-data-row">
          <span class="key-data-label">Target Price (USD)</span>
          <span class="key-data-value">{target_display}</span>
        </div>
        <div class="key-data-row">
          <span class="key-data-label">6m Avg Daily Vol (USD mn)</span>
          <span class="key-data-value">{_fmt_num(avg_vol, 1)}</span>
        </div>
        <div class="key-data-row">
          <span class="key-data-label">Closing Price (USD)</span>
          <span class="key-data-value">{_fmt_num(closing, 2)}</span>
        </div>
        <div class="key-data-row">
          <span class="key-data-label">Market Cap (USD bn)</span>
          <span class="key-data-value">{_fmt_num(mktcap, 1)}</span>
        </div>
        <div class="key-data-row">
          <span class="key-data-label">52-Week Range (USD)</span>
          <span class="key-data-value">{w52_display}</span>
        </div>
        <div class="key-data-row">
          <span class="key-data-label">BVPS (USD)</span>
          <span class="key-data-value">{_fmt_num(bvps, 2)}</span>
        </div>
        <div class="key-data-row">
          <span class="key-data-label">P/E (TTM)</span>
          <span class="key-data-value">{_fmt_num(pe_ratio, 1)}</span>
        </div>
        <div class="key-data-row">
          <span class="key-data-label">EPS (TTM)</span>
          <span class="key-data-value">{_fmt_num(eps_ttm, 2)}</span>
        </div>
      </div>

      <!-- Share Performance : courbe ticker vs benchmark du mandat, 12 mois -->
      <div class="sidebar-card">
        <h3>Share Performance</h3>
        <div class="chart-title">{_esc(ticker)} vs {_esc(data.get("benchmark_label") or "S&P 500")} — Change % Over the Past Year</div>
        {price_svg}
      </div>

      <!-- PE & EPS : 4 dernières années fiscales -->
      <div class="sidebar-card">
        <h3>PE &amp; EPS</h3>
        <div class="chart-title">{_esc(company_name)} PE Ratio and EPS Over the Past 4 Years</div>
        {pe_eps_svg}
      </div>

    </div>
  </div>

  <!-- FOOTER : disclaimer légal -->
  <div class="report-footer">
    &#9888; Ce rapport est genere par AlphaSwarm AI Research.
    Pour usage analytique uniquement.
    Validation humaine requise avant toute decision d&apos;investissement.
  </div>

</div>
</body>
</html>"""

    return html


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║  FONCTION PUBLIQUE 2 : generate_sector_report()                            ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  _SECTOR_CSS_EXTRA — Styles additionnels pour rapports sectoriels          │
# └─────────────────────────────────────────────────────────────────────────────┘
# Ajouté à _BASE_CSS uniquement pour generate_sector_report().
# .sector-metric-row : ligne de métriques dans la sidebar sectorielle
# .alloc-badge       : badge bleu pour l'allocation recommandée (ex: "Surpondérer")

_SECTOR_CSS_EXTRA = """
.sector-metric-row {
    display: flex;
    justify-content: space-between;
    padding: 4px 0;
    border-bottom: 1px dotted #eeeeee;
    font-size: 12px;
}
.sector-metric-row:last-child { border-bottom: none; }
.alloc-badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 3px;
    background: #e8eaf6;
    color: #1a237e;
    font-weight: 700;
    font-size: 12px;
}
"""


# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  generate_sector_report() — Rapport HTML sectoriel                         │
# └─────────────────────────────────────────────────────────────────────────────┘
# Non utilisé en V1 de production (réservé pour une extension future).
# Même structure que generate_company_report() mais orienté secteur :
#   Colonne gauche : Sector Overview, Key Drivers, Valuation, Top Picks, Risks
#   Sidebar : Sector Metrics (Market Cap, Perf YTD, Median P/E, Allocation recommandée)
#             + Graphique performance sectorielle vs benchmark
# Le dict "data" attendu :
#   ticker (code secteur), sector_name, report_date, source
#   sector_overview, key_drivers, valuation_analysis, top_picks, risk_factors
#   sector_market_cap, sector_perf_ytd, sector_pe_median, recommended_allocation
#   sector_series → List[{date, sector_val, benchmark_val}] → SVG

def generate_sector_report(data: dict) -> str:
    """
    Genere un rapport HTML d'analyse sectorielle.

    Parametres
    ----------
    data : dict
        ticker (code secteur), sector_name, report_date, source,
        sector_overview, key_drivers, valuation_analysis, top_picks,
        risk_factors, sector_market_cap, sector_perf_ytd, sector_pe_median,
        recommended_allocation, sector_series (pour graphique).

    Retour
    ------
    str : document HTML autonome.
    """

    # ── BLOC 1 : Extraction des métadonnées ───────────────────────────────────
    sector_code = data.get("ticker", "SECTOR")
    sector_name = data.get("sector_name", sector_code)
    report_date = data.get("report_date", "N/D")
    source      = data.get("source", "AlphaSwarm Research")

    # ── BLOC 2 : Sections narratives ──────────────────────────────────────────
    sector_overview    = data.get("sector_overview", "")
    key_drivers        = data.get("key_drivers", "")
    valuation_analysis = data.get("valuation_analysis", "")
    top_picks_text     = data.get("top_picks", "")
    risk_factors       = data.get("risk_factors", "")

    # ── BLOC 3 : Métriques sidebar ────────────────────────────────────────────
    sector_market_cap       = data.get("sector_market_cap")
    sector_perf_ytd         = data.get("sector_perf_ytd")
    # sector_perf_ytd : float ratio (ex: 0.12 = +12% YTD)
    sector_pe_median        = data.get("sector_pe_median")
    recommended_allocation  = data.get("recommended_allocation")
    # recommended_allocation : string (ex: "Surpondérer", "Neutre", "Sous-pondérer")

    # ── BLOC 4 : Graphique sectoriel ──────────────────────────────────────────
    sector_series = data.get("sector_series", [])
    sector_svg    = _build_sector_perf_svg(sector_series)

    # ── BLOC 5 : Badge allocation ─────────────────────────────────────────────
    alloc_display = (
        f'<span class="alloc-badge">{_esc(recommended_allocation)}</span>'
        if recommended_allocation else "N/D"
        # Affiche le badge coloré ou "N/D" si absent
    )

    # ── BLOC 6 : Assemblage HTML ───────────────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sector Research — {_esc(sector_name)}</title>
<style>
{_BASE_CSS}
{_SECTOR_CSS_EXTRA}
</style>
</head>
<body>
<div class="report-wrapper">

  <!-- HEADER -->
  <div class="report-header">
    <div class="report-header-left">
      <h1>Sector Research Report: {_esc(sector_name)}</h1>
      <div class="subtitle">{_esc(sector_code)} &nbsp;|&nbsp; {_esc(source)}</div>
    </div>
    <div class="report-header-right">
      <div class="logo-text">AlphaSwarm</div>
      <div style="font-size:11px;color:#1a237e;font-weight:600;">alphaswarm.ai</div>
      <div class="report-date">Report date: {_esc(report_date)}</div>
    </div>
  </div>

  <!-- BODY -->
  <div class="report-body">

    <!-- COLONNE GAUCHE (70%) : contenu narratif sectoriel -->
    <div class="col-left">

      <div class="section">
        <h2>Sector Overview</h2>
        <p>{_esc(sector_overview) if sector_overview else "<em>Section non disponible.</em>"}</p>
      </div>

      <div class="section">
        <h2>Key Drivers</h2>
        <p>{_esc(key_drivers) if key_drivers else "<em>Section non disponible.</em>"}</p>
      </div>

      <div class="section">
        <h2>Valuation Analysis</h2>
        <p>{_esc(valuation_analysis) if valuation_analysis else "<em>Section non disponible.</em>"}</p>
      </div>

      <div class="section">
        <h2>Top Picks</h2>
        <p>{_esc(top_picks_text) if top_picks_text else "<em>Section non disponible.</em>"}</p>
      </div>

      <div class="section">
        <h2>Risk Factors</h2>
        <p>{_esc(risk_factors) if risk_factors else "<em>Section non disponible.</em>"}</p>
      </div>

    </div>

    <!-- COLONNE DROITE (30%) : métriques sectorielles + graphique -->
    <div class="col-right">

      <!-- Sector Metrics -->
      <div class="sidebar-card">
        <h3>Sector Metrics</h3>
        <div class="sector-metric-row">
          <span class="key-data-label">Total Market Cap (USD bn)</span>
          <span class="key-data-value">{_fmt_num(sector_market_cap, 1)}</span>
        </div>
        <div class="sector-metric-row">
          <span class="key-data-label">Perf YTD</span>
          <span class="key-data-value">{_fmt_num(sector_perf_ytd, 1, "%") if sector_perf_ytd is not None else "N/D"}</span>
        </div>
        <div class="sector-metric-row">
          <span class="key-data-label">Median P/E</span>
          <span class="key-data-value">{_fmt_num(sector_pe_median, 1)}</span>
        </div>
        <div class="sector-metric-row">
          <span class="key-data-label">Recommended Allocation</span>
          <span class="key-data-value">{alloc_display}</span>
        </div>
      </div>

      <!-- Sector Performance : courbe sectorielle vs benchmark -->
      <div class="sidebar-card">
        <h3>Sector Performance</h3>
        <div class="chart-title">{_esc(sector_name)} vs Benchmark — Change % YTD</div>
        {sector_svg}
      </div>

    </div>
  </div>

  <!-- FOOTER -->
  <div class="report-footer">
    &#9888; Ce rapport est genere par AlphaSwarm AI Research.
    Pour usage analytique uniquement.
    Validation humaine requise avant toute decision d&apos;investissement.
  </div>

</div>
</body>
</html>"""

    return html
