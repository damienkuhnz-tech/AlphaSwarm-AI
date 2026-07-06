"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  AGENTS / RISK MANAGEMENT AGENT — ÉTAPE 4/5                                 ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Rôle : moteur de validation quantitative du portefeuille.                  ║
║  Input  : portfolio (positions), mandate (contraintes risque)               ║
║  Output : RiskReport (PASS/AJUSTER/FAIL + violations + validation complète) ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Architecture "calcul d'abord, jugement ensuite" :                          ║
║    1. quant.run_full_validation() calcule TOUT en Python (déterministe,     ║
║       seedé, reproductible) : backtest 10 ans, train/test 80/20,            ║
║       walk-forward, bootstrap 1000×, Monte Carlo 2000×, stress tests,       ║
║       multi-benchmarks, compliance PASS/FAIL du mandat.                     ║
║    2. Le LLM reçoit un RÉSUMÉ compact et rend un JUGEMENT (statut,          ║
║       violations, recommandations). 1 seul appel LLM (contre 2 avant).      ║
║    3. Garde-fou déterministe : le statut LLM ne peut pas contredire la      ║
║       compliance calculée (un PASS avec des tests FAIL est rétrogradé).     ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Impact sur le workflow (statut retourné dans RiskReport.statut) :          ║
║    PASS    → workflow continue vers Execution                               ║
║    AJUSTER → PortfolioConstructionAgent reboucle (max 3 fois)               ║
║    FAIL    → workflow bloqué, ExecutionAgent sauté                          ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import json
import logging
from typing import Any, Dict, List, Optional

from .base_agent import BaseAgent
from config.prompts import RISK_MANAGEMENT_PROMPT
from models.risk import Backtest, RiskReport
from models.state import PortfolioState
from quant import run_full_validation
from tools.financial_metrics import benchmark_to_etf

logger = logging.getLogger("finagent.agents.risk")


def _pct(x) -> str:
    return f"{x:.2%}" if isinstance(x, (int, float)) else "N/D"


def _num(x) -> str:
    return f"{x:.2f}" if isinstance(x, (int, float)) else "N/D"


class RiskManagementAgent(BaseAgent):

    AGENT_KEY = "risk"
    SYSTEM_PROMPT = RISK_MANAGEMENT_PROMPT
    TOOLS = []  # aucun tool use : tout est calculé en Python avant l'appel LLM

    # ┌─────────────────────────────────────────────────────────────────────────┐
    # │  run() — MÉTHODE PRINCIPALE                                             │
    # └─────────────────────────────────────────────────────────────────────────┘

    def run(self, state: PortfolioState) -> Dict[str, Any]:
        portfolio = state.get("portfolio")
        mandate = state.get("mandate")
        if not portfolio:
            return {"errors": ["Portfolio manquant — Portfolio Construction Agent requis"]}
        if not mandate:
            return {"errors": ["Mandate manquant"]}

        # ── 1. VALIDATION QUANTITATIVE COMPLÈTE (Python, source de vérité) ────
        positions = [{"ticker": p.ticker, "poids": p.poids} for p in portfolio.positions]
        bench_etf = benchmark_to_etf(mandate.benchmark)
        quant = run_full_validation(
            positions, mandate, portfolio,
            benchmark_etf=bench_etf, benchmark_name=mandate.benchmark,
        )
        quant_ok = quant.get("statut") == "OK"

        # Concentrations : dérivées des poids, disponibles même sans données marché
        poids_tries = sorted((p["poids"] for p in positions), reverse=True)
        conc = {
            "top1":  round(sum(poids_tries[:1]), 4),
            "top5":  round(sum(poids_tries[:5]), 4),
            "top10": round(sum(poids_tries[:10]), 4),
        }

        # ── 2. JUGEMENT LLM (1 appel, sur résumé compact) ─────────────────────
        user_msg = self._build_judgment_prompt(portfolio, mandate, quant, conc)
        raw = self._call_llm_with_retry(user_msg)
        data = self._parse_json(raw)

        # ── 3. FORÇAGE DES MÉTRIQUES CALCULÉES (le LLM ne contrôle pas les     ─
        #      chiffres, seulement le jugement) ─────────────────────────────────
        perf = quant.get("performance") or {}
        mr = data.get("metriques_risque")
        if not isinstance(mr, dict):
            mr = {}
        mr["concentration_top1"]     = _pct(conc["top1"])
        mr["concentration_top5"]     = _pct(conc["top5"])
        mr["concentration_top10"]    = _pct(conc["top10"])
        mr["volatilite_estimee"]     = _pct(perf.get("volatilite")) if quant_ok else "N/D"
        mr["tracking_error_estimee"] = _pct(perf.get("tracking_error")) if quant_ok else "N/D"
        mr["beta_estime"]            = _num(perf.get("beta")) if quant_ok else "N/D"
        mr["benchmark_utilise"]      = bench_etf
        mr["periode"]                = (quant.get("meta") or {}).get("periode", "")
        mr.setdefault("exposition_sectorielle",
                      portfolio.repartition_sectorielle.model_dump())
        data["metriques_risque"] = mr

        # ── 4. COHÉRENCE STATUT ↔ COMPLIANCE (garde-fou déterministe) ─────────
        compliance = quant.get("compliance") or {}
        data["violations"] = self._merge_violations(
            data.get("violations"), compliance)
        statut_llm = data.get("statut")
        if quant_ok and compliance.get("n_fail", 0) > 0 and statut_llm == "PASS":
            logger.warning("Statut LLM PASS incohérent avec %d tests FAIL → AJUSTER",
                           compliance["n_fail"])
            data["statut"] = "AJUSTER"
        if quant_ok and compliance.get("n_fail", 0) == 0 and statut_llm == "FAIL":
            # Un FAIL sans aucun test échoué n'est pas justifiable objectivement.
            data["statut"] = "PASS"

        # ── 5. RAPPORT LEGACY + VALIDATION COMPLÈTE ───────────────────────────
        data["backtest"] = self._legacy_backtest(quant, bench_etf)
        data["validation_quantitative"] = quant if quant_ok else {
            "statut": "ERREUR", "message": quant.get("message", "calcul indisponible"),
        }
        data.setdefault("commentaire_backtest", "")

        risk_report = RiskReport(**data)
        return {"risk_report": risk_report, "current_step": "execution"}

    # ┌─────────────────────────────────────────────────────────────────────────┐
    # │  Construction du prompt de jugement (résumé compact, ~1500 tokens)     │
    # └─────────────────────────────────────────────────────────────────────────┘

    def _build_judgment_prompt(self, portfolio, mandate, quant: Dict,
                               conc: Dict) -> str:
        br = mandate.budget_risque

        contraintes = (
            f"- Poids max/position : {mandate.poids_max_par_position:.0%}\n"
            f"- Tracking error max : {br.tracking_error_max:.0%}\n"
            f"- Volatilité max : {br.volatilite_max:.0%} | Drawdown max : {br.drawdown_max:.0%}\n"
            f"- Beta : [{br.beta_min}, {br.beta_max}] | Top10 max : {br.concentration_top10_max:.0%}\n"
            f"- Positions cible : {mandate.nombre_positions_cible} | "
            f"Cash : [{mandate.cash_min:.0%}, {mandate.cash_max:.0%}]"
        )

        top_positions = sorted(portfolio.positions, key=lambda p: -p.poids)[:10]
        positions_txt = ", ".join(f"{p.ticker} {p.poids:.1%}" for p in top_positions)
        secteurs = {k: f"{v:.0%}" for k, v in
                    portfolio.repartition_sectorielle.model_dump().items()
                    if isinstance(v, (int, float)) and v > 0.001}

        if quant.get("statut") != "OK":
            return f"""Analyse le risque du portefeuille suivant.

PORTEFEUILLE ({portfolio.nombre_positions} positions, cash {portfolio.cash_poids:.1%}) :
Top 10 : {positions_txt}
Secteurs : {json.dumps(secteurs, ensure_ascii=False)}
Concentrations top1/top5/top10 : {_pct(conc['top1'])} / {_pct(conc['top5'])} / {_pct(conc['top10'])}

CONTRAINTES DU MANDAT :
{contraintes}

⚠️ Le moteur quantitatif est INDISPONIBLE ({quant.get('message', 'données manquantes')}).
Juge uniquement sur la structure (concentrations, secteurs, nombre de positions, cash).
Sois prudent : sans métriques de marché, préfère AJUSTER à PASS en cas de doute.

Retourne UNIQUEMENT le JSON du schéma RiskReport."""

        perf = quant["performance"]
        tt = quant.get("train_test") or {}
        wf = quant.get("walk_forward") or {}
        boot = quant.get("bootstrap") or {}
        mc = quant.get("monte_carlo") or {}
        compliance = quant.get("compliance") or {}

        # Tests de compliance : seul le verdict et les échecs sont détaillés
        fails = [t for t in compliance.get("tests", []) if t["statut"] == "FAIL"]
        fails_txt = "\n".join(
            f"  ✗ {t['nom']} : {t['valeur']} (limite {t['limite']})" for t in fails
        ) or "  (aucun)"

        oos = tt.get("out_of_sample") or {}
        ins = tt.get("in_sample") or {}
        stress_lines = "\n".join(
            f"  - {s['nom']} : {_pct(s.get('rendement'))} "
            f"(bench {_pct(s.get('rendement_benchmark'))}, DD {_pct(s.get('max_drawdown'))})"
            for s in quant.get("stress_tests", []) if s.get("statut") == "OK"
        )
        alea = (quant.get("benchmarks") or {}).get("test_aleatoire") or {}

        return f"""Analyse le risque du portefeuille suivant et rends ton verdict.

PORTEFEUILLE ({portfolio.nombre_positions} positions, cash {portfolio.cash_poids:.1%}) :
Top 10 : {positions_txt}
Secteurs : {json.dumps(secteurs, ensure_ascii=False)}

CONTRAINTES DU MANDAT :
{contraintes}

COMPLIANCE CALCULÉE (Python) : {compliance.get('statut_global')} — \
{compliance.get('n_pass')} PASS / {compliance.get('n_fail')} FAIL / {compliance.get('n_na')} N-A
Tests en échec :
{fails_txt}

MÉTRIQUES GLOBALES ({perf.get('debut')} → {perf.get('fin')}, rebalancement mensuel) :
- CAGR {_pct(perf.get('cagr'))} | Vol {_pct(perf.get('volatilite'))} | Sharpe {_num(perf.get('sharpe'))} | Sortino {_num(perf.get('sortino'))}
- Beta {_num(perf.get('beta'))} | Alpha {_pct(perf.get('alpha'))} | TE {_pct(perf.get('tracking_error'))} | IR {_num(perf.get('information_ratio'))}
- Max drawdown {_pct(perf.get('max_drawdown'))} | VaR95 1j {_pct(perf.get('var_95'))} | CVaR95 {_pct(perf.get('cvar_95'))}
- Concentrations top1/top5/top10 : {_pct(conc['top1'])} / {_pct(conc['top5'])} / {_pct(conc['top10'])}

VALIDATION OUT-OF-SAMPLE (split 80/20) :
- In-sample  : CAGR {_pct(ins.get('cagr'))}, Sharpe {_num(ins.get('sharpe'))}
- Out-of-sample : CAGR {_pct(oos.get('cagr'))}, Sharpe {_num(oos.get('sharpe'))}

WALK-FORWARD ({wf.get('nb_fenetres', 0)} fenêtres) :
- CAGR moyen {_pct((wf.get('cagr') or {}).get('moyenne'))} ± {_pct((wf.get('cagr') or {}).get('ecart_type'))}
- Fenêtres profitables : {_pct(wf.get('stabilite'))}

BOOTSTRAP ({boot.get('n_simulations', 0)} simulations) :
- Sharpe médian {_num((boot.get('sharpe') or {}).get('mediane'))}, IC95 [{_num((boot.get('sharpe') or {}).get('ci_bas'))} ; {_num((boot.get('sharpe') or {}).get('ci_haut'))}]
- Probabilité de battre le benchmark : {_pct(boot.get('prob_batre_benchmark'))}

MONTE CARLO ({mc.get('n_simulations', 0)} trajectoires, 1 an) :
- Probabilité de perte : {_pct(mc.get('prob_perte'))} | VaR95 1 an : {_pct(mc.get('var_95_1an'))}

STRESS TESTS HISTORIQUES :
{stress_lines}

TEST PLACEBO : le Sharpe du portefeuille se situe au percentile \
{_pct(alea.get('percentile_portefeuille'))} de {alea.get('n_portefeuilles', 0)} portefeuilles aléatoires.

Rends ton verdict (statut, violations, recommandations actionnables, commentaire,
commentaire_backtest incluant les limites méthodologiques).
Retourne UNIQUEMENT le JSON du schéma RiskReport."""

    # ┌─────────────────────────────────────────────────────────────────────────┐
    # │  Helpers                                                                │
    # └─────────────────────────────────────────────────────────────────────────┘

    @staticmethod
    def _merge_violations(llm_violations, compliance: Dict) -> List[dict]:
        """
        Fusionne les violations du LLM avec celles dérivées MÉCANIQUEMENT des
        tests de compliance FAIL (garantit qu'aucun échec calculé n'est omis).
        """
        # Normalisation des sévérités LLM hors vocabulaire (ex: "MODEREE",
        # "ELEVEE") vers le Literal du modèle — évite une ValidationError.
        sev_map = {
            "MINEURE": "MINEURE", "FAIBLE": "MINEURE", "BASSE": "MINEURE",
            "MAJEURE": "MAJEURE", "MODEREE": "MAJEURE", "MODÉRÉE": "MAJEURE",
            "ELEVEE": "MAJEURE", "ÉLEVÉE": "MAJEURE", "HAUTE": "MAJEURE",
            "CRITIQUE": "CRITIQUE", "SEVERE": "CRITIQUE", "SÉVÈRE": "CRITIQUE",
            "INFORMATIVE": "INFORMATIVE", "INFO": "INFORMATIVE",
        }
        merged: List[dict] = []
        seen = set()
        for v in (llm_violations or []):
            if isinstance(v, dict) and v.get("type"):
                sev = str(v.get("severite", "")).strip().upper()
                v["severite"] = sev_map.get(sev, "MAJEURE")
                merged.append(v)
                seen.add(str(v.get("type", "")).lower()[:20])
        for t in compliance.get("tests", []):
            if t["statut"] != "FAIL":
                continue
            key = t["nom"].lower()[:20]
            if any(key in s or s in key for s in seen):
                continue
            merged.append({
                "type": t["nom"],
                "detail": f"{t['nom']} mesuré à {t['valeur']} pour une limite de {t['limite']}",
                "action": "Repondérer le portefeuille pour revenir dans la limite",
                "severite": "MAJEURE",
            })
        return merged

    @staticmethod
    def _legacy_backtest(quant: Dict, bench_etf: str) -> Backtest:
        """Convertit le rapport quant au format Backtest historique (rétro-compat UI)."""
        if quant.get("statut") != "OK":
            return Backtest(statut="ERREUR", message=quant.get("message", ""),
                            benchmark_utilise=bench_etf)
        perf = quant["performance"]
        courbe = [
            {"i": i, "date": pt.get("date"),
             "port": pt.get("port"), "bench": pt.get("bench")}
            for i, pt in enumerate(quant.get("courbe_valeur", []))
        ]
        return Backtest(
            statut="OK",
            rendement_total=perf.get("rendement_total"),
            rendement_benchmark=perf.get("rendement_benchmark"),
            surperformance=perf.get("surperformance"),
            volatilite_realisee=perf.get("volatilite"),
            sharpe=perf.get("sharpe"),
            max_drawdown=perf.get("max_drawdown"),
            courbe_valeur=courbe,
            tickers_exclus=(quant.get("structure") or {}).get("tickers_exclus", []),
            jours=perf.get("jours"),
            benchmark_utilise=bench_etf,
            periode=(quant.get("meta") or {}).get("periode", ""),
        )
