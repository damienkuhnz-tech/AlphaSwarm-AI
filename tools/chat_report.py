"""
Générateur de rapports equity research à la demande (depuis le chat).
Claude génère l'analyse complète. yfinance + Tavily fournissent les données réelles.
Produit HTML standalone dark-mode + PDF via reportlab.
"""

import os
import json
import datetime
import html as html_lib
from pathlib import Path

# ── Palette ──────────────────────────────────────────────────────────────────
BG      = "#1A1A2E"
SURFACE = "#16213E"
CARD    = "#0F3460"
BLUE    = "#00D4FF"
GREEN   = "#00E676"
RED     = "#FF5252"
ORANGE  = "#FFB74D"
TEXT    = "#FFFFFF"
TEXT2   = "#B0BEC5"
MUTED   = "#78909C"
BORDER  = "#2A3A5E"
ROW_ALT = "#1E2A4A"


# ══════════════════════════════════════════════════════════════════════════════
# STEP 1 — Fetch market data
# ══════════════════════════════════════════════════════════════════════════════

def _fetch_market_data(ticker: str) -> dict:
    data = {
        "ticker": ticker.upper(),
        "name": ticker.upper(),
        "price": None, "currency": "USD",
        "market_cap": None, "pe_ratio": None, "eps": None,
        "dividend": None, "week52_high": None, "week52_low": None,
        "beta": None, "revenue": None, "net_income": None,
        "operating_margin": None, "roe": None,
        "description": "", "sector": None, "industry": None,
        "financials": [], "news": [],
        "yf_url": f"https://finance.yahoo.com/quote/{ticker.upper()}",
    }
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        info = t.info or {}
        data["name"]             = info.get("longName") or info.get("shortName") or ticker.upper()
        data["price"]            = info.get("currentPrice") or info.get("regularMarketPrice")
        data["currency"]         = info.get("currency", "USD")
        data["market_cap"]       = info.get("marketCap")
        data["pe_ratio"]         = info.get("trailingPE") or info.get("forwardPE")
        data["eps"]              = info.get("trailingEps")
        data["dividend"]         = info.get("dividendYield")
        data["week52_high"]      = info.get("fiftyTwoWeekHigh")
        data["week52_low"]       = info.get("fiftyTwoWeekLow")
        data["beta"]             = info.get("beta")
        data["revenue"]          = info.get("totalRevenue")
        data["net_income"]       = info.get("netIncomeToCommon")
        data["operating_margin"] = info.get("operatingMargins")
        data["roe"]              = info.get("returnOnEquity")
        data["description"]      = info.get("longBusinessSummary") or ""
        data["sector"]           = info.get("sector")
        data["industry"]         = info.get("industry")
        try:
            inc = t.financials
            if inc is not None and not inc.empty:
                for col in inc.columns[:4]:
                    year = str(col)[:4]
                    rev = inc.loc["Total Revenue", col] if "Total Revenue" in inc.index else None
                    ni  = inc.loc["Net Income", col]    if "Net Income"    in inc.index else None
                    ebit = inc.loc["EBIT", col]         if "EBIT"          in inc.index else None
                    data["financials"].append({
                        "year": year,
                        "revenue": _fmt_mil(rev),
                        "net_income": _fmt_mil(ni),
                        "ebit": _fmt_mil(ebit),
                    })
        except Exception:
            pass
    except Exception as e:
        print(f"[chat_report] yfinance error: {e}")

    try:
        from config.settings import settings as cfg
        from tavily import TavilyClient
        if cfg.TAVILY_API_KEY:
            client = TavilyClient(api_key=cfg.TAVILY_API_KEY)
            results = client.search(
                query=f"{ticker} stock earnings results 2025 2026 analyst",
                max_results=6, search_depth="basic"
            )
            for r in (results.get("results") or [])[:6]:
                data["news"].append({
                    "title": r.get("title", ""),
                    "url":   r.get("url", ""),
                    "snippet": r.get("content", "")[:200],
                    "date":  (r.get("published_date") or "")[:10],
                })
    except Exception as e:
        print(f"[chat_report] Tavily error: {e}")

    return data


# ══════════════════════════════════════════════════════════════════════════════
# STEP 2 — Claude generates the full analysis
# ══════════════════════════════════════════════════════════════════════════════

def _generate_analysis_with_claude(data: dict, lang: str = "fr") -> dict:
    """
    Appelle Claude pour générer l'analyse complète du rapport.
    Retourne un dict avec toutes les sections analytiques.
    """
    from config.settings import settings as cfg
    from llm.client import get_client

    ticker = data["ticker"]
    name   = data["name"]

    # Construire le contexte avec les données disponibles
    mkt_ctx = f"""
Ticker: {ticker}
Nom: {name}
Cours actuel: {_fmt_price(data.get('price'), data.get('currency','USD'))}
Market Cap: {_fmt_mil(data.get('market_cap'))}
P/E: {data.get('pe_ratio', 'N/D')}
EPS: {data.get('eps', 'N/D')}
Beta: {data.get('beta', 'N/D')}
Secteur: {data.get('sector', 'N/D')}
Industrie: {data.get('industry', 'N/D')}
Marge opérationnelle: {_fmt_pct(data.get('operating_margin'))}
ROE: {_fmt_pct(data.get('roe'))}
Description: {(data.get('description') or '')[:500]}
Historique financier: {json.dumps(data.get('financials', []))}
Actualités récentes: {json.dumps([n.get('title','') + ' — ' + n.get('snippet','') for n in data.get('news', [])])}
"""

    prompt = f"""Tu es un analyste equity research senior buy-side. Génère un rapport complet sur {name} ({ticker}).

DONNÉES DE MARCHÉ DISPONIBLES:
{mkt_ctx}

Génère une analyse JSON avec EXACTEMENT ces clés (en {'français' if lang == 'fr' else 'anglais'}):
{{
  "rating": "STRONG BUY | BUY | HOLD | SELL | STRONG SELL",
  "price_target": "cours cible en USD (ex: $185)",
  "upside": "potentiel en % (ex: +32%)",
  "investment_thesis": "paragraphe de 150 mots sur la thèse d'investissement, les avantages concurrentiels, les catalyseurs",
  "catalysts": ["catalyseur 1", "catalyseur 2", "catalyseur 3", "catalyseur 4"],
  "business_segments": [
    {{"name": "segment", "revenue_pct": "X%", "growth": "+X%", "comment": "description courte"}}
  ],
  "competitive_position": "paragraphe de 100 mots sur le positionnement concurrentiel et le moat",
  "dcf_assumptions": {{
    "revenue_growth_y1": "X%",
    "revenue_growth_y2": "X%",
    "revenue_growth_y3": "X%",
    "terminal_growth": "X%",
    "wacc": "X%",
    "operating_margin_terminal": "X%"
  }},
  "dcf_result": {{
    "intrinsic_value": "$XXX",
    "upside_vs_current": "X%",
    "methodology": "phrase courte sur la méthodologie"
  }},
  "risks": [
    {{"level": "ÉLEVÉ", "title": "titre du risque", "description": "description 50 mots"}},
    {{"level": "ÉLEVÉ", "title": "...", "description": "..."}},
    {{"level": "MOYEN", "title": "...", "description": "..."}},
    {{"level": "MOYEN", "title": "...", "description": "..."}},
    {{"level": "FAIBLE", "title": "...", "description": "..."}}
  ],
  "forecasts": [
    {{"year": "2025E", "revenue": "$XXB", "growth": "+X%", "op_margin": "X%", "net_income": "$XXB", "eps": "$XX"}},
    {{"year": "2026E", "revenue": "$XXB", "growth": "+X%", "op_margin": "X%", "net_income": "$XXB", "eps": "$XX"}},
    {{"year": "2027E", "revenue": "$XXB", "growth": "+X%", "op_margin": "X%", "net_income": "$XXB", "eps": "$XX"}}
  ],
  "conclusion": "paragraphe de synthèse de 100 mots avec recommandation argumentée"
}}

Réponds UNIQUEMENT avec le JSON valide, sans markdown, sans texte avant ou après."""

    try:
        client = get_client()
        response = client.messages.create(
            model=cfg.MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = response.content[0].text.strip()
        # Nettoyer si Claude a quand même mis du markdown
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw)
    except Exception as e:
        print(f"[chat_report] Claude error: {e}")
        return _fallback_analysis(ticker, lang)


def _fallback_analysis(ticker: str, lang: str) -> dict:
    """Analyse de secours si Claude échoue."""
    return {
        "rating": "À ANALYSER",
        "price_target": "N/D",
        "upside": "N/D",
        "investment_thesis": "Analyse non disponible. Veuillez réessayer.",
        "catalysts": ["Données insuffisantes"],
        "business_segments": [],
        "competitive_position": "Analyse non disponible.",
        "dcf_assumptions": {},
        "dcf_result": {"intrinsic_value": "N/D", "upside_vs_current": "N/D", "methodology": "N/D"},
        "risks": [],
        "forecasts": [],
        "conclusion": "Analyse non disponible. Veuillez réessayer.",
    }


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _fmt_mil(val) -> str:
    if val is None: return "N/D"
    try:
        v = float(val)
        if abs(v) >= 1e12: return f"${v/1e12:.1f}T"
        if abs(v) >= 1e9:  return f"${v/1e9:.1f}B"
        if abs(v) >= 1e6:  return f"${v/1e6:.1f}M"
        return f"${v:,.0f}"
    except: return str(val)

def _fmt_pct(val) -> str:
    if val is None or val == "N/D": return "N/D"
    try: return f"{float(val)*100:.1f}%"
    except: return str(val)

def _fmt_price(val, currency="USD") -> str:
    if val is None or val == "N/D": return "N/D"
    sym = "$" if currency in ("USD","") else ("€" if currency == "EUR" else f"{currency} ")
    try: return f"{sym}{float(val):,.2f}"
    except: return str(val)

def _esc(v) -> str:
    if v is None: return "N/D"
    return html_lib.escape(str(v))

def _rating_color(rating: str) -> str:
    r = rating.upper()
    if "STRONG BUY" in r: return GREEN
    if "BUY" in r: return GREEN
    if "HOLD" in r: return ORANGE
    if "SELL" in r: return RED
    return BLUE

def _risk_color(level: str) -> str:
    l = level.upper()
    if "ÉLEVÉ" in l or "HIGH" in l: return RED
    if "MOYEN" in l or "MED" in l: return ORANGE
    return GREEN


# ══════════════════════════════════════════════════════════════════════════════
# STEP 3 — HTML Generator
# ══════════════════════════════════════════════════════════════════════════════

_CSS = f"""
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ background:{BG}; color:{TEXT2}; font-family:'Segoe UI',system-ui,sans-serif; font-size:13px; line-height:1.6; }}
.page {{ max-width:1000px; margin:0 auto; padding:32px 24px; }}
.rpt-header {{ background:{CARD}; border-bottom:2px solid {BLUE}; padding:24px 32px; display:flex; justify-content:space-between; align-items:center; margin-bottom:32px; border-radius:8px; }}
.rpt-title {{ font-size:22px; font-weight:700; color:{TEXT}; }}
.rpt-ticker {{ font-size:32px; font-weight:700; color:{BLUE}; letter-spacing:2px; }}
.rpt-date {{ font-size:11px; color:{MUTED}; margin-top:4px; }}
.section {{ margin-bottom:36px; }}
.section-title {{ font-size:14px; font-weight:700; color:{BLUE}; text-transform:uppercase; letter-spacing:1.5px; border-bottom:1px solid {BLUE}33; padding-bottom:8px; margin-bottom:16px; }}
.rating-box {{ background:{CARD}; border:2px solid {BLUE}; border-radius:8px; padding:20px 28px; display:inline-flex; gap:40px; align-items:center; margin-bottom:24px; flex-wrap:wrap; }}
.rating-item {{ text-align:center; }}
.rating-label {{ font-size:10px; color:{MUTED}; text-transform:uppercase; letter-spacing:1px; }}
.rating-value {{ font-size:20px; font-weight:700; color:{TEXT}; margin-top:4px; }}
.kpi-grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(150px,1fr)); gap:10px; margin-bottom:24px; }}
.kpi-card {{ background:{SURFACE}; border:1px solid {BORDER}; border-radius:6px; padding:12px; }}
.kpi-label {{ font-size:10px; color:{MUTED}; text-transform:uppercase; letter-spacing:1px; }}
.kpi-value {{ font-size:15px; font-weight:700; color:{TEXT}; margin-top:3px; }}
table {{ width:100%; border-collapse:collapse; font-size:12px; margin-bottom:8px; }}
thead tr {{ background:{CARD}; }}
thead th {{ color:{TEXT}; font-weight:600; padding:8px 10px; text-align:left; border:1px solid {BORDER}; }}
tbody tr:nth-child(even) {{ background:{ROW_ALT}; }}
tbody tr {{ background:{SURFACE}; }}
tbody td {{ color:{TEXT2}; padding:7px 10px; border:1px solid {BORDER}; }}
.tbl-source {{ font-size:10px; color:{MUTED}; margin-top:4px; margin-bottom:16px; }}
.thesis-box {{ background:{SURFACE}; border-left:3px solid {BLUE}; padding:16px 20px; border-radius:0 6px 6px 0; margin-bottom:16px; line-height:1.8; color:{TEXT2}; }}
.catalyst-list {{ list-style:none; padding:0; }}
.catalyst-list li {{ background:{SURFACE}; border-left:3px solid {GREEN}; padding:10px 14px; margin-bottom:8px; border-radius:0 4px 4px 0; color:{TEXT2}; }}
.catalyst-list li::before {{ content:"→ "; color:{GREEN}; font-weight:700; }}
.risk-item {{ padding:10px 14px; margin-bottom:8px; border-radius:0 4px 4px 0; }}
.risk-title {{ font-weight:700; font-size:12px; margin-bottom:4px; }}
.risk-body {{ font-size:12px; color:{TEXT2}; }}
.news-item {{ background:{SURFACE}; border-left:3px solid {BLUE}33; padding:10px 14px; margin-bottom:8px; border-radius:0 4px 4px 0; }}
.news-title {{ color:{TEXT}; font-weight:600; font-size:12px; }}
.news-meta {{ font-size:10px; color:{MUTED}; margin-top:2px; }}
.news-link {{ color:{BLUE}; text-decoration:none; font-size:11px; }}
.pos {{ color:{GREEN}; font-weight:600; }}
.neg {{ color:{RED}; font-weight:600; }}
.conclusion-box {{ background:{CARD}; border:2px solid {BLUE}; border-radius:8px; padding:20px 24px; }}
.conclusion-rec {{ font-size:11px; color:{MUTED}; text-transform:uppercase; letter-spacing:1px; }}
.disclaimer {{ font-size:10px; color:{MUTED}; border-top:1px solid {BORDER}; padding-top:16px; margin-top:32px; line-height:1.6; }}
.two-col {{ display:grid; grid-template-columns:1fr 1fr; gap:20px; }}
@media(max-width:700px) {{ .two-col {{ grid-template-columns:1fr; }} .rating-box {{ gap:16px; }} }}
"""


def generate_html_report(mkt: dict, ai: dict, lang: str = "fr") -> str:
    t     = _esc(mkt["ticker"])
    name  = _esc(mkt["name"])
    date  = datetime.datetime.now().strftime("%d/%m/%Y")
    price = _fmt_price(mkt.get("price"), mkt.get("currency","USD"))
    yf_url = _esc(mkt.get("yf_url",""))
    rating = _esc(ai.get("rating","À ANALYSER"))
    rc = _rating_color(rating)

    # KPI cards
    kpis = [
        ("Cours", price),
        ("Market Cap", _fmt_mil(mkt.get("market_cap"))),
        ("P/E Ratio", str(mkt.get("pe_ratio","N/D") or "N/D")),
        ("EPS", str(mkt.get("eps","N/D") or "N/D")),
        ("Dividende", _fmt_pct(mkt.get("dividend"))),
        ("Beta", str(mkt.get("beta","N/D") or "N/D")),
        ("52s Haut", _fmt_price(mkt.get("week52_high"), mkt.get("currency","USD"))),
        ("52s Bas",  _fmt_price(mkt.get("week52_low"),  mkt.get("currency","USD"))),
        ("Secteur",  _esc(mkt.get("sector","N/D"))),
        ("Marge Op.", _fmt_pct(mkt.get("operating_margin"))),
    ]
    kpi_html = "".join(f'<div class="kpi-card"><div class="kpi-label">{k}</div><div class="kpi-value">{v}</div></div>' for k,v in kpis)

    # Catalysts
    cats = ai.get("catalysts") or []
    cats_html = "<ul class='catalyst-list'>" + "".join(f"<li>{_esc(c)}</li>" for c in cats) + "</ul>"

    # Business segments
    segs = ai.get("business_segments") or []
    seg_rows = "".join(f"<tr><td>{_esc(s.get('name',''))}</td><td>{_esc(s.get('revenue_pct',''))}</td><td class='pos'>{_esc(s.get('growth',''))}</td><td>{_esc(s.get('comment',''))}</td></tr>" for s in segs)
    seg_table = f"""<table><thead><tr><th>Segment</th><th>% CA</th><th>Croissance</th><th>Commentaire</th></tr></thead><tbody>{seg_rows if seg_rows else '<tr><td colspan="4" style="color:'+MUTED+';text-align:center">N/D</td></tr>'}</tbody></table>""" if segs else "<p style='color:"+MUTED+"'>Données de segmentation non disponibles.</p>"

    # Financials table
    fin = mkt.get("financials") or []
    fin_rows = "".join(f"<tr><td>{_esc(f.get('year',''))}</td><td>{_esc(f.get('revenue',''))}</td><td>{_esc(f.get('net_income',''))}</td><td>{_esc(f.get('ebit',''))}</td></tr>" for f in fin)
    fin_table = f"""<table><thead><tr><th>Année</th><th>Chiffre d'Affaires</th><th>Résultat Net</th><th>EBIT</th></tr></thead><tbody>{fin_rows if fin_rows else '<tr><td colspan="4" style="color:'+MUTED+';text-align:center">Données non disponibles</td></tr>'}</tbody></table>"""

    # DCF
    dcf_a = ai.get("dcf_assumptions") or {}
    dcf_r = ai.get("dcf_result") or {}
    dcf_rows = "".join(f"<tr><td>{_esc(k)}</td><td>{_esc(v)}</td></tr>" for k,v in dcf_a.items() if v)
    dcf_table = f"""<table><thead><tr><th>Hypothèse</th><th>Valeur</th></tr></thead><tbody>{dcf_rows if dcf_rows else '<tr><td colspan="2" style="color:'+MUTED+'">N/D</td></tr>'}</tbody></table>"""
    dcf_result_html = f"""<div class="rating-box" style="margin-top:12px;">
      <div class="rating-item"><div class="rating-label">Valeur Intrinsèque</div><div class="rating-value" style="color:{BLUE}">{_esc(dcf_r.get('intrinsic_value','N/D'))}</div></div>
      <div class="rating-item"><div class="rating-label">Upside DCF</div><div class="rating-value" style="color:{GREEN}">{_esc(dcf_r.get('upside_vs_current','N/D'))}</div></div>
    </div>"""

    # Risks
    risks = ai.get("risks") or []
    risks_html = ""
    for r in risks:
        rc2 = _risk_color(r.get("level",""))
        risks_html += f"""<div class="risk-item" style="background:{rc2}18;border-left:4px solid {rc2};">
          <div class="risk-title" style="color:{rc2}">[{_esc(r.get('level',''))}] {_esc(r.get('title',''))}</div>
          <div class="risk-body">{_esc(r.get('description',''))}</div>
        </div>"""

    # Forecasts
    fcs = ai.get("forecasts") or []
    fc_rows = "".join(f"<tr><td><b>{_esc(f.get('year',''))}</b></td><td>{_esc(f.get('revenue',''))}</td><td class='pos'>{_esc(f.get('growth',''))}</td><td>{_esc(f.get('op_margin',''))}</td><td>{_esc(f.get('net_income',''))}</td><td>{_esc(f.get('eps',''))}</td></tr>" for f in fcs)
    fc_table = f"""<table><thead><tr><th>Année</th><th>CA</th><th>Croissance</th><th>Marge Op.</th><th>Résultat Net</th><th>BPA</th></tr></thead><tbody>{fc_rows if fc_rows else '<tr><td colspan="6" style="color:'+MUTED+';text-align:center">N/D</td></tr>'}</tbody></table>"""

    # News
    news_html = ""
    for n in (mkt.get("news") or [])[:5]:
        news_html += f"""<div class="news-item">
          <div class="news-title">{_esc(n.get('title',''))}</div>
          <div class="news-meta">{_esc(n.get('date',''))} &nbsp;·&nbsp; <a class="news-link" href="{_esc(n.get('url','#'))}" target="_blank">Source →</a></div>
        </div>"""
    if not news_html:
        news_html = f'<p style="color:{MUTED}">Aucune actualité disponible.</p>'

    rating_color = _rating_color(ai.get("rating",""))

    return f"""<!DOCTYPE html>
<html lang="{lang}">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{t} — Rapport Equity Research</title>
<style>{_CSS}</style>
</head>
<body><div class="page">

<div class="rpt-header">
  <div>
    <div class="rpt-title">Rapport Equity Research</div>
    <div style="font-size:16px;color:{TEXT2};margin-top:4px;">{name}</div>
    <div class="rpt-date">Généré le {date} · <a href="{yf_url}" target="_blank" style="color:{BLUE};">Yahoo Finance</a></div>
  </div>
  <div class="rpt-ticker">{t}</div>
</div>

<!-- RATING -->
<div class="section">
  <div class="section-title">Recommandation</div>
  <div class="rating-box">
    <div class="rating-item"><div class="rating-label">Rating</div><div class="rating-value" style="color:{rating_color};font-size:24px;">{_esc(ai.get('rating','N/D'))}</div></div>
    <div class="rating-item"><div class="rating-label">Cours Cible</div><div class="rating-value">{_esc(ai.get('price_target','N/D'))}</div></div>
    <div class="rating-item"><div class="rating-label">Potentiel</div><div class="rating-value" style="color:{GREEN}">{_esc(ai.get('upside','N/D'))}</div></div>
    <div class="rating-item"><div class="rating-label">Cours Actuel</div><div class="rating-value">{price}</div></div>
  </div>
</div>

<!-- MÉTRIQUES -->
<div class="section">
  <div class="section-title">Snapshot de Marché</div>
  <div class="kpi-grid">{kpi_html}</div>
  <div class="tbl-source">Source : <a href="{yf_url}" target="_blank" style="color:{BLUE};">Yahoo Finance</a></div>
</div>

<!-- THÈSE -->
<div class="section">
  <div class="section-title">Thèse d'Investissement</div>
  <div class="thesis-box">{_esc(ai.get('investment_thesis',''))}</div>
  <div style="margin-top:16px;font-size:12px;font-weight:600;color:{TEXT};margin-bottom:8px;">Catalyseurs Clés</div>
  {cats_html}
</div>

<!-- SEGMENTS -->
<div class="section">
  <div class="section-title">Segments d'Activité</div>
  {seg_table}
  <div style="margin-top:12px;color:{TEXT2};font-size:12px;">{_esc(ai.get('competitive_position',''))}</div>
</div>

<!-- FINANCIERS -->
<div class="section">
  <div class="section-title">Performance Financière Historique</div>
  {fin_table}
  <div class="tbl-source">Source : <a href="{yf_url}" target="_blank" style="color:{BLUE};">Yahoo Finance Financials</a></div>
</div>

<!-- DCF -->
<div class="section">
  <div class="section-title">Valorisation DCF</div>
  <div class="two-col">
    <div>{dcf_table}</div>
    <div>{dcf_result_html}</div>
  </div>
  <div style="font-size:11px;color:{MUTED};margin-top:8px;">{_esc((ai.get('dcf_result') or {}).get('methodology',''))}</div>
</div>

<!-- PRÉVISIONS -->
<div class="section">
  <div class="section-title">Prévisions 3 Ans</div>
  {fc_table}
</div>

<!-- RISQUES -->
<div class="section">
  <div class="section-title">Principaux Risques</div>
  {risks_html if risks_html else f'<p style="color:{MUTED}">Analyse des risques non disponible.</p>'}
</div>

<!-- ACTUALITÉS -->
<div class="section">
  <div class="section-title">Actualités Récentes</div>
  {news_html}
</div>

<!-- CONCLUSION -->
<div class="section">
  <div class="section-title">Conclusion</div>
  <div class="conclusion-box">
    <div class="conclusion-rec">Recommandation Finale</div>
    <div style="font-size:22px;font-weight:700;color:{rating_color};margin:6px 0 12px;">{_esc(ai.get('rating','N/D'))} — Cible {_esc(ai.get('price_target','N/D'))} ({_esc(ai.get('upside','N/D'))})</div>
    <div style="color:{TEXT2};font-size:13px;line-height:1.7;">{_esc(ai.get('conclusion',''))}</div>
  </div>
</div>

<div class="disclaimer">⚠ Ce rapport est produit à titre informatif uniquement et ne constitue pas un conseil en investissement. AlphaSwarm ne peut être tenu responsable des décisions prises sur la base de ce document. Investir comporte des risques de perte en capital.</div>

</div></body></html>"""


# ══════════════════════════════════════════════════════════════════════════════
# STEP 4 — PDF Generator
# ══════════════════════════════════════════════════════════════════════════════

def generate_pdf_report(mkt: dict, ai: dict, output_path: str, lang: str = "fr") -> bool:
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.colors import HexColor
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, PageBreak, HRFlowable
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.enums import TA_JUSTIFY, TA_CENTER, TA_LEFT
        from reportlab.lib.units import inch
        # reportlab.pdfgen.canvas n'est plus nécessaire — on utilise onFirstPage/onLaterPages

        W, H = letter
        ticker = mkt["ticker"]
        name   = mkt["name"]
        date   = datetime.datetime.now().strftime("%d/%m/%Y")
        rating = ai.get("rating", "À ANALYSER")

        def sty(name, **kw):
            d = dict(fontName="Helvetica", fontSize=9, textColor=HexColor(TEXT2), leading=14, spaceAfter=4)
            d.update(kw)
            return ParagraphStyle(name, **d)

        s_title  = sty("t",  fontSize=18, textColor=HexColor(TEXT),  fontName="Helvetica-Bold", spaceAfter=8)
        s_h1     = sty("h1", fontSize=12, textColor=HexColor(BLUE),  fontName="Helvetica-Bold", spaceAfter=6)
        s_body   = sty("b",  fontSize=9,  textColor=HexColor(TEXT2), alignment=TA_JUSTIFY, spaceAfter=6)
        s_muted  = sty("m",  fontSize=8,  textColor=HexColor(MUTED), spaceAfter=4)
        s_green  = sty("g",  fontSize=14, textColor=HexColor(GREEN), fontName="Helvetica-Bold", alignment=TA_CENTER)
        s_blue   = sty("bl", fontSize=12, textColor=HexColor(BLUE),  fontName="Helvetica-Bold")

        def tbl(data_rows):
            t = Table(data_rows, repeatRows=1)
            t.setStyle(TableStyle([
                ("BACKGROUND",    (0,0), (-1,0),  HexColor(CARD)),
                ("TEXTCOLOR",     (0,0), (-1,0),  HexColor(TEXT)),
                ("FONTNAME",      (0,0), (-1,0),  "Helvetica-Bold"),
                ("FONTSIZE",      (0,0), (-1,-1), 8),
                ("ROWBACKGROUNDS",(0,1), (-1,-1), [HexColor(SURFACE), HexColor(ROW_ALT)]),
                ("TEXTCOLOR",     (0,1), (-1,-1), HexColor(TEXT2)),
                ("GRID",          (0,0), (-1,-1), 0.4, HexColor(BORDER)),
                ("BOX",           (0,0), (-1,-1), 1.0, HexColor(BLUE)),
                ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
                ("TOPPADDING",    (0,0), (-1,-1), 4),
                ("BOTTOMPADDING", (0,0), (-1,-1), 4),
                ("LEFTPADDING",   (0,0), (-1,-1), 6),
            ]))
            return t

        def _header_footer(canvas, doc_obj):
            """Dessine header + footer sur chaque page."""
            canvas.saveState()
            # Header
            canvas.setFillColor(HexColor(CARD))
            canvas.rect(0, H-48, W, 48, fill=1, stroke=0)
            canvas.setFillColor(HexColor(BLUE))
            canvas.rect(0, H-50, W, 2, fill=1, stroke=0)
            canvas.setFillColor(HexColor(TEXT))
            canvas.setFont("Helvetica-Bold", 9)
            canvas.drawString(28, H-28, f"{name}  —  Equity Research Report")
            canvas.setFont("Helvetica-Bold", 13)
            canvas.setFillColor(HexColor(BLUE))
            canvas.drawRightString(W-28, H-30, ticker)
            # Footer
            canvas.setFillColor(HexColor(SURFACE))
            canvas.rect(0, 0, W, 28, fill=1, stroke=0)
            canvas.setFillColor(HexColor(BLUE))
            canvas.rect(0, 28, W, 1, fill=1, stroke=0)
            canvas.setFillColor(HexColor(MUTED))
            canvas.setFont("Helvetica", 7)
            canvas.drawString(28, 9, f"AlphaSwarm · {date} · Rapport informationnel uniquement")
            canvas.drawRightString(W-28, 9, f"Page {doc_obj.page}")
            canvas.restoreState()

        doc = SimpleDocTemplate(output_path, pagesize=letter,
            leftMargin=0.6*inch, rightMargin=0.6*inch, topMargin=0.85*inch, bottomMargin=0.55*inch)

        story = []
        sp = lambda h=8: Spacer(1, h)
        hr = lambda: HRFlowable(width="100%", thickness=0.5, color=HexColor(BORDER), spaceAfter=8)

        # Cover
        story += [
            Paragraph(f"{ticker} — Rapport Equity Research", s_title),
            Paragraph(name, sty("sub", fontSize=12, textColor=HexColor(TEXT2))),
            sp(4), Paragraph(f"Généré le {date}", s_muted), sp(12), hr(),
        ]

        # Rating box
        rc = _rating_color(rating)
        rating_data = [
            [Paragraph("Rating", s_muted), Paragraph("Cours Cible", s_muted), Paragraph("Potentiel", s_muted), Paragraph("Cours Actuel", s_muted)],
            [Paragraph(f"<b>{_esc(rating)}</b>", sty("rv", fontSize=13, textColor=HexColor(rc), fontName="Helvetica-Bold", alignment=TA_CENTER)),
             Paragraph(f"<b>{_esc(ai.get('price_target','N/D'))}</b>", sty("rv2", fontSize=13, textColor=HexColor(TEXT), fontName="Helvetica-Bold", alignment=TA_CENTER)),
             Paragraph(f"<b>{_esc(ai.get('upside','N/D'))}</b>", sty("rv3", fontSize=13, textColor=HexColor(GREEN), fontName="Helvetica-Bold", alignment=TA_CENTER)),
             Paragraph(f"<b>{_fmt_price(mkt.get('price'), mkt.get('currency','USD'))}</b>", sty("rv4", fontSize=13, textColor=HexColor(BLUE), fontName="Helvetica-Bold", alignment=TA_CENTER))],
        ]
        rt = Table(rating_data, colWidths=[1.8*inch]*4)
        rt.setStyle(TableStyle([
            ("BACKGROUND",    (0,0), (-1,-1), HexColor(CARD)),
            ("BOX",           (0,0), (-1,-1), 1.5, HexColor(BLUE)),
            ("GRID",          (0,0), (-1,-1), 0.3, HexColor(BORDER)),
            ("ALIGN",         (0,0), (-1,-1), "CENTER"),
            ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
            ("TOPPADDING",    (0,0), (-1,-1), 8),
            ("BOTTOMPADDING", (0,0), (-1,-1), 8),
        ]))
        story += [rt, sp(16), PageBreak()]

        # KPI
        story += [Paragraph("Snapshot de Marché", s_h1), hr()]
        kpi_rows = [
            [Paragraph("Métrique", sty("kh", fontSize=8, textColor=HexColor(TEXT), fontName="Helvetica-Bold")),
             Paragraph("Valeur",   sty("kh2", fontSize=8, textColor=HexColor(TEXT), fontName="Helvetica-Bold"))],
            ["Cours", _fmt_price(mkt.get("price"), mkt.get("currency","USD"))],
            ["Market Cap", _fmt_mil(mkt.get("market_cap"))],
            ["P/E Ratio", str(mkt.get("pe_ratio") or "N/D")],
            ["EPS", str(mkt.get("eps") or "N/D")],
            ["Beta", str(mkt.get("beta") or "N/D")],
            ["52s Haut", _fmt_price(mkt.get("week52_high"), mkt.get("currency","USD"))],
            ["52s Bas",  _fmt_price(mkt.get("week52_low"),  mkt.get("currency","USD"))],
            ["Secteur", str(mkt.get("sector") or "N/D")],
            ["Marge Opérationnelle", _fmt_pct(mkt.get("operating_margin"))],
            ["ROE", _fmt_pct(mkt.get("roe"))],
        ]
        story += [tbl(kpi_rows), sp(16)]

        # Thesis
        story += [Paragraph("Thèse d'Investissement", s_h1), hr(),
                  Paragraph(_esc(ai.get("investment_thesis","")), s_body), sp(8)]
        cats = ai.get("catalysts") or []
        for c in cats:
            story.append(Paragraph(f"→  {_esc(c)}", sty("cat", fontSize=9, textColor=HexColor(GREEN), spaceAfter=4)))
        story += [sp(16), PageBreak()]

        # Financials
        story += [Paragraph("Performance Financière", s_h1), hr()]
        fin = mkt.get("financials") or []
        if fin:
            fin_rows = [[Paragraph(h, sty("fh", fontSize=8, textColor=HexColor(TEXT), fontName="Helvetica-Bold")) for h in ["Année","CA","Résultat Net","EBIT"]]]
            fin_rows += [[f.get("year",""), f.get("revenue",""), f.get("net_income",""), f.get("ebit","")] for f in fin]
            story.append(tbl(fin_rows))
        else:
            story.append(Paragraph("Données financières non disponibles.", s_muted))
        story += [sp(16)]

        # DCF
        story += [Paragraph("Valorisation DCF", s_h1), hr()]
        dcf_a = ai.get("dcf_assumptions") or {}
        dcf_r = ai.get("dcf_result") or {}
        if dcf_a:
            dcf_rows = [[Paragraph(h, sty("dh", fontSize=8, textColor=HexColor(TEXT), fontName="Helvetica-Bold")) for h in ["Hypothèse","Valeur"]]]
            dcf_rows += [[k, str(v)] for k,v in dcf_a.items() if v]
            story.append(tbl(dcf_rows))
        story += [sp(8),
                  Paragraph(f"Valeur intrinsèque : <b>{_esc(dcf_r.get('intrinsic_value','N/D'))}</b>  —  Upside DCF : <b>{_esc(dcf_r.get('upside_vs_current','N/D'))}</b>",
                             sty("dcfr", fontSize=10, textColor=HexColor(BLUE))),
                  sp(16), PageBreak()]

        # Forecasts
        story += [Paragraph("Prévisions 3 Ans", s_h1), hr()]
        fcs = ai.get("forecasts") or []
        if fcs:
            fc_rows = [[Paragraph(h, sty("fch", fontSize=8, textColor=HexColor(TEXT), fontName="Helvetica-Bold")) for h in ["Année","CA","Croissance","Marge Op.","Résultat Net","BPA"]]]
            fc_rows += [[f.get("year",""), f.get("revenue",""), f.get("growth",""), f.get("op_margin",""), f.get("net_income",""), f.get("eps","")] for f in fcs]
            story.append(tbl(fc_rows))
        else:
            story.append(Paragraph("Prévisions non disponibles.", s_muted))
        story.append(sp(16))

        # Risks
        story += [Paragraph("Principaux Risques", s_h1), hr()]
        for r in (ai.get("risks") or []):
            rc2 = _risk_color(r.get("level",""))
            story.append(Paragraph(f"<b>[{_esc(r.get('level',''))}] {_esc(r.get('title',''))}</b>", sty("rtl", fontSize=9, textColor=HexColor(rc2), fontName="Helvetica-Bold")))
            story.append(Paragraph(_esc(r.get("description","")), s_body))
            story.append(sp(4))
        story += [sp(16), PageBreak()]

        # Conclusion
        story += [Paragraph("Conclusion & Recommandation", s_h1), hr()]
        concl_data = [
            [Paragraph("RECOMMANDATION FINALE", sty("cl", fontSize=8, textColor=HexColor(MUTED)))],
            [Paragraph(f"{_esc(rating)} — Cible {_esc(ai.get('price_target','N/D'))} ({_esc(ai.get('upside','N/D'))})", sty("crv", fontSize=14, textColor=HexColor(_rating_color(rating)), fontName="Helvetica-Bold", alignment=TA_CENTER))],
            [Paragraph(_esc(ai.get("conclusion","")), s_body)],
        ]
        ct = Table(concl_data, colWidths=[7*inch])
        ct.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,-1), HexColor(CARD)),
            ("BOX",        (0,0), (-1,-1), 1.5, HexColor(BLUE)),
            ("LEFTPADDING",(0,0), (-1,-1), 14),
            ("TOPPADDING", (0,0), (-1,-1), 10),
            ("BOTTOMPADDING",(0,0),(-1,-1),10),
        ]))
        story += [ct, sp(20),
                  Paragraph("⚠ Ce rapport est produit à titre informatif uniquement et ne constitue pas un conseil en investissement. Investir comporte des risques de perte en capital.",
                             sty("disc", fontSize=7, textColor=HexColor(MUTED)))]

        doc.build(story, onFirstPage=_header_footer, onLaterPages=_header_footer)
        return True
    except Exception as e:
        print(f"[chat_report] PDF error: {e}")
        return False


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def generate_report(ticker: str, lang: str = "fr", outputs_dir: str = "outputs") -> dict:
    ticker = ticker.upper().strip()
    date   = datetime.datetime.now().strftime("%Y-%m")
    out_dir = Path(outputs_dir) / "chat_reports"
    out_dir.mkdir(parents=True, exist_ok=True)

    html_filename = f"{ticker}_Research_{date}.html"
    pdf_filename  = f"{ticker}_Research_{date}.pdf"
    html_path = str(out_dir / html_filename)
    pdf_path  = str(out_dir / pdf_filename)

    # 1. Données marché
    mkt = _fetch_market_data(ticker)

    # 2. Analyse Claude
    ai = _generate_analysis_with_claude(mkt, lang=lang)

    # 3. HTML
    try:
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(generate_html_report(mkt, ai, lang=lang))
    except Exception as e:
        return {"error": f"HTML error: {e}"}

    # 4. PDF
    pdf_ok = generate_pdf_report(mkt, ai, pdf_path, lang=lang)

    return {
        "ticker":   ticker,
        "name":     mkt.get("name", ticker),
        "html_url": f"/api/chat-report/file/{html_filename}",
        "pdf_url":  f"/api/chat-report/file/{pdf_filename}" if pdf_ok else None,
        "error":    None,
    }
