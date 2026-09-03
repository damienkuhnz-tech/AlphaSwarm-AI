"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  AGENTS / PORTFOLIO CONSTRUCTION AGENT - ÉTAPE 3/5                          ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Rôle : construire le portefeuille optimal à partir des analyses Research.  ║
║  Input  : research (analyses), mandate (contraintes), risk_report (iter>1)  ║
║  Output : PortfolioOutput (positions avec poids et valeurs USD)              ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Peut tourner plusieurs fois : boucle Risk ↔ Portfolio dans workflow.py.    ║
║  À chaque itération > 1, il reçoit les violations du Risk Agent pour        ║
║  construire une version corrigée du portefeuille.                           ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""
# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  IMPORTS                                                                    │
# └─────────────────────────────────────────────────────────────────────────────┘

import json
from typing import Any, Dict
from .base_agent import BaseAgent
from config.prompts import PORTFOLIO_CONSTRUCTION_PROMPT
from models.state import PortfolioState
from models.portfolio import PortfolioOutput


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║  CLASSE PORTFOLIOCONSTRUCTIONAGENT                                          ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

class PortfolioConstructionAgent(BaseAgent):

    AGENT_KEY = "portfolio"
    SYSTEM_PROMPT = PORTFOLIO_CONSTRUCTION_PROMPT
    # Rôle : "portfolio manager quantitatif" chargé de maximiser le ratio
    # rendement/risque en respectant les contraintes du mandat.

    # MAX_TOKENS_OVERRIDE : cet agent produit le plus gros JSON du workflow
    # (jusqu'à ~45 positions détaillées). Le plafond global (settings.MAX_TOKENS=4000)
    # tronque la réponse → crash "Unterminated string". On élargit SON budget à 8000
    # sans toucher aux autres agents (cf. BaseAgent.__init__). Lu par getattr().
    MAX_TOKENS_OVERRIDE = 8000

    # Pas de TOOLS : le LLM raisonne à partir des analyses Research.
    # Les données de marché ont déjà été fetchées par EquityResearchAgent.

    # ┌─────────────────────────────────────────────────────────────────────────┐
    # │  run() - MÉTHODE PRINCIPALE                                             │
    # └─────────────────────────────────────────────────────────────────────────┘

    def run(self, state: PortfolioState) -> Dict[str, Any]:

        # ── BLOC 1 : Lecture des inputs ───────────────────────────────────────
        research    = state.get("research", [])
        mandate     = state.get("mandate")
        risk_report = state.get("risk_report")
        # risk_report = None à la 1ère itération (pas encore de Risk Agent tourné)
        # risk_report = RiskReport à partir de l'itération 2 (contient les violations)

        # Briefing PM : conversation avant construction (niveau 3 d'interaction).
        # Format : list[{"role": "user"|"assistant", "content": str}]
        # Si vide → comportement standard (l'agent construit avec son jugement).
        # Si rempli → l'agent doit suivre les directives échangées avec le PM.
        portfolio_briefing = state.get("portfolio_briefing") or []

        iteration = state.get("portfolio_iteration", 1)
        # Numéro de l'itération courante (injecté par workflow.py avant chaque appel).
        # Itération 1 : construction initiale
        # Itération 2+ : correction des violations du Risk Agent

        # ── BLOC 2 : Pré-conditions ───────────────────────────────────────────
        if not research:
            return {"errors": ["Research manquant - Equity Research Agent requis"]}
        if not mandate:
            return {"errors": ["Mandate manquant"]}

        # ── BLOC 3 : Résumé de TOUTES les analyses (matière première) ─────────
        # L'agent reçoit l'univers COMPLET (BUY / HOLD / SELL). La recommandation
        # est un SIGNAL de priorisation, PAS un filtre d'éligibilité : l'agent
        # sélectionne lui-même les titres pour construire une allocation cohérente
        # (il peut écarter un BUY redondant ou retenir un HOLD pour diversifier).
        # Tri par score_conviction décroissant : meilleurs signaux en tête.
        # Champs bornés (l'univers ≈ 1.5× la cible, jusqu'à ~50 titres) pour ne
        # pas diluer l'attention du LLM ni gonfler inutilement le prompt.
        analyses_sorted = sorted(research, key=lambda r: r.score_conviction, reverse=True)
        analyses_summary = json.dumps(
            [
                {
                    "ticker":           r.ticker,
                    "nom":              r.nom,
                    "recommandation":   r.recommandation,        # SIGNAL, pas filtre
                    "score_conviction": r.score_conviction,      # 0-100 : force du signal
                    "poids_suggere":    r.poids_suggere_initial,
                    "upside":           getattr(r.valorisation, "upside_potentiel", None) or "N/D",
                    "methode_valo":     getattr(r.valorisation, "methode_principale", "") or "N/D",
                    "risques_cles":     (r.risques_cles or [])[:2],
                    "catalyseurs":      (r.catalyseurs or [])[:2],
                    "these_resume":     (r.these_investissement or "")[:140],
                }
                for r in analyses_sorted
            ],
            ensure_ascii=False, indent=2
        )

        # ── BLOC 3b : Bloc briefing PM (niveau 3 - conversation avant build) ──
        # Si le PM a échangé avec l'agent avant de cliquer "Construire",
        # on injecte la conversation comme contexte directif. Le LLM doit
        # respecter les choix exprimés (titres écartés, surpondérations, etc.).
        briefing_block = ""
        if portfolio_briefing:
            transcript_lines = []
            for msg in portfolio_briefing:
                role = msg.get("role", "user")
                content = msg.get("content", "").strip()
                if not content:
                    continue
                label = "PM" if role == "user" else "AGENT"
                transcript_lines.append(f"[{label}] {content}")
            transcript = "\n".join(transcript_lines)
            briefing_block = f"""
DIRECTIVES DU PORTFOLIO MANAGER (briefing préalable) :
La conversation suivante a eu lieu entre le Portfolio Manager et toi avant la construction.
Tu dois respecter STRICTEMENT les choix et préférences exprimés par le PM
(titres à exclure, à surpondérer, contraintes additionnelles, biais sectoriels demandés).
Si un choix du PM contredit le mandat, signale-le mais respecte-le tout en restant dans
les contraintes dures du mandat (capital, poids min/max, cash min/max).

--- DÉBUT TRANSCRIPT ---
{transcript}
--- FIN TRANSCRIPT ---
"""

        # ── BLOC 4 : Bloc de corrections (itérations > 1 uniquement) ──────────
        # Si le Risk Agent a retourné AJUSTER, on injecte les violations
        # dans le prompt pour que le LLM construise un portefeuille corrigé.
        corrections_block = ""  # Vide par défaut (itération 1)

        if risk_report and iteration > 1:
            # On ne fournit les corrections QUE si c'est une ré-itération.
            # risk_report.violations : liste des ViolationRisque (type, detail, action, severite)
            # risk_report.recommandations : liste de strings (ex: "Réduire Techno de 32% à 28%")
            corrections_block = f"""
CORRECTIONS REQUISES PAR LE RISK AGENT (itération {iteration}) :
Violations à corriger :
{json.dumps([v.model_dump() for v in risk_report.violations], ensure_ascii=False, indent=2)}

Recommandations :
{chr(10).join(f"- {r}" for r in risk_report.recommandations)}
"""
            # chr(10) = "\n" : concatène les recommandations ligne par ligne
            # (les f-strings ne supportent pas le backslash dans les accolades)

        # ── BLOC 5 : Construction du prompt ───────────────────────────────────
        # Pré-calcul hors f-string (évite TypeError Python 3.12+ avec {{}} imbriqués)
        contraintes_json = json.dumps(
            {k: {"max": v.max, "min": v.min} for k, v in mandate.contraintes_sectorielles.items()},
            indent=2, ensure_ascii=False
        )

        # ── Poids max EFFECTIF : résout la tension cible-basse vs poids_max ────
        # Si peu de positions, poids_max du mandat (pensé pour 25-30 lignes) rend
        # l'investissement intégral impossible (ex: 6 × 7% = 42% → 58% de cash forcé,
        # ce qui viole cash_max). On relève alors poids_max juste assez pour pouvoir
        # investir (1 - cash_min) sur le nombre cible de positions.
        import re as _re
        _nums = [int(n) for n in _re.findall(r"\d+", str(mandate.nombre_positions_cible))]
        _nb_cible = max(_nums) if _nums else 10
        _invest_requis = 1.0 - (mandate.cash_min or 0.0)
        _poids_max_requis = _invest_requis / _nb_cible if _nb_cible else mandate.poids_max_par_position
        poids_max_effectif = max(mandate.poids_max_par_position, round(_poids_max_requis, 4))
        # Si poids_max suffit déjà (cible élevée), on garde celui du mandat.

        user_msg = f"""
Tu reçois ci-dessous l'INTÉGRALITÉ des analyses de recherche (BUY, HOLD et SELL).
Ce n'est PAS une liste figée à pondérer : c'est ta matière première. À TOI de
SÉLECTIONNER les titres et de construire une allocation COHÉRENTE qui respecte le
mandat ET les directives du PM (briefing ci-dessous). La recommandation est un
SIGNAL de priorisation, pas un filtre : tu peux écarter un BUY redondant/corrélé et
retenir un HOLD pour diversifier ou équilibrer le portefeuille. Justifie tout choix
notable s'écartant du signal Research dans decisions_notables.

⚠️ CONTRAINTE PRIORITAIRE - NOMBRE DE POSITIONS : {mandate.nombre_positions_cible}
Le portefeuille DOIT contenir ce nombre de positions (cf. règle "NOMBRE DE POSITIONS").

ANALYSES DE RECHERCHE (univers complet - BUY / HOLD / SELL) :
{analyses_summary}

MANDAT :
- Capital total    : {mandate.capital:,.0f} USD
- Poids max/pos    : {poids_max_effectif:.1%}
- Poids min/pos    : {mandate.poids_min_par_position:.0%}
- Cash min/max     : {mandate.cash_min:.0%} / {mandate.cash_max:.0%}
- Positions cible  : {mandate.nombre_positions_cible}
- Limite turnover  : {mandate.limite_turnover:.0%}

CONTRAINTES SECTORIELLES :
{contraintes_json}
{briefing_block}{corrections_block}

Retourne UNIQUEMENT le JSON correspondant au schéma PortfolioOutput.
"""
        # ── BLOC 6 : Appel LLM ────────────────────────────────────────────────
        raw  = self._call_llm_with_retry(user_msg)
        data = self._parse_json(raw)

        # ── BLOC 7 : Normalisation de la structure JSON ───────────────────────
        # Problème fréquent : le LLM encapsule parfois sa réponse dans une clé
        # supplémentaire. Ex: {"portfolio": {"positions": [...]}} au lieu de
        # {"positions": [...]}. Ces blocs déballent les structures imbriquées.

        for key in ("portfolio", "portefeuille"):
            if key in data and "positions" not in data:
                # Le LLM a mis les données dans data["portfolio"] au lieu de data directement
                inner = data.pop(key)       # Extrait le contenu
                if isinstance(inner, dict):
                    data.update(inner)      # Merge au niveau supérieur
                elif isinstance(inner, list):
                    data["positions"] = inner  # C'est directement la liste de positions

        # Si positions est encore un dict imbriqué (cas rare mais observé)
        if isinstance(data.get("positions"), dict):
            inner = data["positions"]
            data.update(inner)
            # Ex: data["positions"] = {"items": [...]} → on merge et on récupère items

        # Normalise la liste de positions : ne garde que les dicts valides
        if isinstance(data.get("positions"), list):
            normalized = []
            for p in data["positions"]:
                if isinstance(p, dict):
                    normalized.append(p)
                # Si p n'est pas un dict (ex: string ou None) → ignoré silencieusement
            data["positions"] = normalized

        # ── BLOC 8 : Enrichissement et construction Pydantic ──────────────────
        data["iteration"] = iteration
        # Injecte le numéro d'itération dans les données avant validation Pydantic.
        # PortfolioOutput.iteration = 1 (initial), 2, 3 (corrections)

        # ── BLOC 8b : Forçage du capital (source de vérité = mandat) ──────────
        # Le LLM "oublie" parfois la magnitude (retourne 100 000 au lieu de
        # 100 000 000 → portefeuille affiché à 95k$ au lieu de 95M$). On ne lui
        # fait donc PAS confiance pour les montants : capital_total vient du
        # mandat, et chaque valeur_usd est recalculée depuis le poids.
        # (Même principe que MandateAgent qui force data["capital"] = capital.)
        capital = mandate.capital
        data["capital_total"] = capital
        cash_poids = data.get("cash_poids", 0.05) or 0.05

        # ── Normalisation des poids (corrige le sur/sous-investissement) ──────
        # Le LLM ne garantit pas que Σ poids = (1 − cash). Sur de grands univers,
        # il a tendance à sur-investir (ex: 29 lignes → Σ = 130%, ce qui donne un
        # portefeuille à 134% du capital, impossible en long-only). On rescale donc
        # les poids pour que leur somme égale exactement la part investie (1 − cash),
        # ce qui garantit un portefeuille bouclé à 100% du capital.
        positions = [p for p in data.get("positions", []) if isinstance(p, dict)]
        somme_poids = sum((p.get("poids") or 0.0) for p in positions)
        cible_investie = max(0.0, 1.0 - cash_poids)
        if somme_poids > 0 and cible_investie > 0:
            facteur = cible_investie / somme_poids
            for p in positions:
                p["poids"] = round((p.get("poids") or 0.0) * facteur, 4)
            # Réajuste le cash pour absorber l'arrondi et boucler à 100%.
            cash_poids = round(1.0 - sum(p["poids"] for p in positions), 4)
            data["cash_poids"] = cash_poids

        data["cash_valeur_usd"] = capital * cash_poids
        for p in data.get("positions", []):
            if isinstance(p, dict):
                p["valeur_usd"] = capital * (p.get("poids") or 0.0)

        portfolio = PortfolioOutput(**data)
        # Pydantic valide et convertit les types :
        #   - model_post_init convertit repartition_sectorielle dict → objet
        #   - model_post_init compte nombre_positions si = 0
        #   - Position.poids est validé entre 0.0 et 1.0

        # ── BLOC 9 : Retour dans le state ─────────────────────────────────────
        return {
            "portfolio":          portfolio,
            # workflow.py le passera à RiskManagementAgent

            "portfolio_iteration": iteration + 1,
            # Incrémente pour la prochaine itération éventuelle.
            # Si Risk = PASS → ce compteur ne sert plus.
            # Si Risk = AJUSTER → workflow.py reboucle avec cette valeur incrémentée.

            "current_step": "risk",
            # Étape suivante : RiskManagementAgent
        }