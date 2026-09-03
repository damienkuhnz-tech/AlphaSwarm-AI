"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  AGENTS / MANDATE AGENT - ÉTAPE 1/5                                         ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Rôle : formaliser le mandat d'investissement en règles précises.           ║
║  Input  : strategie, capital, benchmark, horizon (depuis state initial)     ║
║  Output : MandateOutput (univers, contraintes, budget risque, ESG)          ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Conception : le prompt inclut le template JSON EXACT attendu.              ║
║  Raison : les LLM respectent mieux une structure montrée que décrite.       ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  IMPORTS                                                                    │
# └─────────────────────────────────────────────────────────────────────────────┘

import json
from typing import Any, Dict
from .base_agent import BaseAgent
from config.prompts import MANDATE_PROMPT
from models.state import PortfolioState
from models.mandate import MandateOutput
from tools.sector_beta import (
    build_sector_weights,
    get_sector_classification,
    RISK_PROFILE_BETA,
)


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║  CLASSE MANDATEAGENT                                                        ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

class MandateAgent(BaseAgent):

    AGENT_KEY = "mandate"
    SYSTEM_PROMPT = MANDATE_PROMPT
    # Rôle LLM : "compliance officer / risk manager senior"
    # Instructions : formaliser un mandat institutionnel complet en JSON.

    # Pas de TOOLS : le mandat est généré par raisonnement pur.
    # Les valeurs (30% max Techno, tracking error 5%...) sont des standards
    # de l'industrie que le LLM connaît intrinsèquement.

    # ┌─────────────────────────────────────────────────────────────────────────┐
    # │  run() - MÉTHODE PRINCIPALE                                             │
    # └─────────────────────────────────────────────────────────────────────────┘

    def run(self, state: PortfolioState) -> Dict[str, Any]:

        # ── BLOC 1 : Lecture des 4 inputs depuis le state ─────────────────────
        # Ces valeurs viennent de main.py (argparse). Ce sont les seules entrées
        # disponibles au démarrage du workflow (avant tout agent).
        strategie = state.get("strategie", "long-only equity global")
        capital   = state.get("capital",   100_000_000)
        benchmark = state.get("benchmark", "MSCI World")
        horizon   = state.get("horizon",   "3-5 ans")

        # ── BLOC 2 : Lecture du profil de risque ──────────────────────────────
        # Le profil est fourni par le form utilisateur (state) ou "equilibre" par défaut.
        profil_risque = state.get("profil_risque", "equilibre").lower()
        perte_max     = state.get("perte_max_toleree")   # ex: 15.0 → -15% toléré
        priorite      = state.get("priorite_principale", "croissance")
        nb_positions_cible = state.get("nombre_positions_cible")  # int|None (saisi par le gérant)

        # ── BLOC 2b : Réconciliation profil/beta ──────────────────────────────
        # Si l'utilisateur a saisi des betas explicitement incompatibles avec le
        # profil_risque sélectionné dans le dropdown, on recalibre le profil
        # effectif à partir des betas. Les betas font foi car ils reflètent
        # l'intention quantitative réelle du PM.
        #
        # Règle : on se base sur beta_min_override pour inférer le profil.
        #   beta_min >= 1.25 → "agressif"
        #   beta_min >= 1.05 → "dynamique"
        #   beta_min >= 0.80 → "equilibre"
        #   beta_min >= 0.60 → "modere"
        #   sinon           → "conservateur"
        beta_min_override = state.get("beta_min_override")
        beta_max_override = state.get("beta_max_override")

        if beta_min_override is not None:
            if beta_min_override >= 1.25:
                profil_from_beta = "agressif"
            elif beta_min_override >= 1.05:
                profil_from_beta = "dynamique"
            elif beta_min_override >= 0.80:
                profil_from_beta = "equilibre"
            elif beta_min_override >= 0.60:
                profil_from_beta = "modere"
            else:
                profil_from_beta = "conservateur"

            if profil_from_beta != profil_risque:
                # Conflit détecté → le beta override le dropdown
                # Ex: dropdown="conservateur" + beta_min=1.5 → profil effectif="agressif"
                profil_risque = profil_from_beta

        # ── BLOC 3 : Paramètres de budget risque adaptatifs au profil ──────────
        # Chaque profil correspond à des standards institutionnels reconnus.
        # Un fonds conservateur UCITS n'aura jamais vol_max=18% ou beta=1.2.
        _RISK_PARAMS = {
            "conservateur": {
                "te": 0.03, "vol": 0.12, "dd": 0.12,
                "beta_min": 0.40, "beta_max": 0.85, "top10": 0.45,
                "description": "Préservation du capital - secteurs défensifs uniquement",
            },
            "modere": {
                "te": 0.04, "vol": 0.15, "dd": 0.15,
                "beta_min": 0.60, "beta_max": 1.05, "top10": 0.50,
                "description": "Équilibre rendement/risque - mix défensif/croissance",
            },
            "equilibre": {
                "te": 0.05, "vol": 0.18, "dd": 0.20,
                "beta_min": 0.80, "beta_max": 1.20, "top10": 0.55,
                "description": "Croissance long terme - diversifié tous secteurs",
            },
            "dynamique": {
                "te": 0.07, "vol": 0.22, "dd": 0.25,
                "beta_min": 0.90, "beta_max": 1.35, "top10": 0.60,
                "description": "Performance prioritaire - secteurs croissance et cycliques",
            },
            "agressif": {
                "te": 0.10, "vol": 0.28, "dd": 0.35,
                "beta_min": 1.00, "beta_max": 1.55, "top10": 0.65,
                "description": "Rendement maximal - haute concentration, forte volatilité",
            },
        }
        rp = _RISK_PARAMS.get(profil_risque, _RISK_PARAMS["equilibre"])

        # Si l'utilisateur a saisi une perte max tolérée plus conservative,
        # on la prend comme plafond sur le drawdown_max.
        dd_max = rp["dd"]
        if perte_max is not None:
            dd_max = min(dd_max, perte_max / 100)

        # Si des betas override ont été fournis, on les applique directement
        # au budget risque plutôt que d'utiliser les valeurs du _RISK_PARAMS.
        # Cela garantit que le mandat généré reflète EXACTEMENT l'intention du PM.
        effective_beta_min = beta_min_override if beta_min_override is not None else rp["beta_min"]
        effective_beta_max = beta_max_override if beta_max_override is not None else rp["beta_max"]

        # ── BLOC 4 : Segmentation sectorielle quantitative par beta ───────────
        # build_sector_weights() calcule les poids max/min par secteur
        # en fonction de la compatibilité beta avec le profil.
        # PRIMARY   → poids distribués équitablement (max plafonné)
        # SECONDARY → poids limités (max_pct_secteur_secondaire)
        # EXCLUDED  → max = 0.00
        sector_weights = build_sector_weights(profil_risque)
        classif        = get_sector_classification(profil_risque)
        profile_data   = RISK_PROFILE_BETA.get(profil_risque, RISK_PROFILE_BETA["equilibre"])

        # Sérialise les poids calculés en JSON pour le template
        contraintes_sectorielles_json = json.dumps(
            {s: {"max": w["max"], "min": w["min"]}
             for s, w in sector_weights.items()},
            ensure_ascii=False, indent=4
        )

        # Résumé lisible : secteurs primaires, secondaires, exclus
        primary_names   = ", ".join(classif["primary"].keys())   or "aucun"
        secondary_names = ", ".join(classif["secondary"].keys()) or "aucun"
        excluded_names  = ", ".join(classif["excluded"].keys())  or "aucun"

        # ── BLOC 5 : Construction du prompt avec template JSON ─────────────────
        user_msg = f"""
Définis le mandat d'investissement pour les paramètres suivants :

- Stratégie      : {strategie}
- Capital géré   : {capital:,.0f} USD
- Benchmark      : {benchmark}
- Horizon        : {horizon}
- Profil risque  : {profil_risque.upper()} - {rp['description']}
- Priorité       : {priorite}

BUDGET RISQUE IMPOSÉ - PROFIL {profil_risque.upper()} :
  • Tracking Error max      = {rp['te']*100:.0f}%
  • Volatilité annuelle max = {rp['vol']*100:.0f}%
  • Drawdown max toléré     = {dd_max*100:.0f}%
  • Beta portefeuille cible = {profile_data['beta_cible_portefeuille']}

SEGMENTATION SECTORIELLE (calculée par compatibilité beta) :
  Secteurs PRIMAIRES   (beta compatible)  : {primary_names}
  Secteurs SECONDAIRES (overlap partiel)  : {secondary_names}
  Secteurs EXCLUS      (beta incompatible): {excluded_names}
  → Minimum {profile_data['min_secteurs']} secteurs distincts obligatoires dans le portefeuille.
  → Total secteurs secondaires plafonné à {profile_data['max_pct_total_secondaire']}% du portefeuille.

Retourne UNIQUEMENT un JSON avec EXACTEMENT ces champs (pas d'autres) :
{{
  "strategie": "{strategie}",
  "benchmark": "{benchmark}",
  "horizon": "{horizon}",
  "capital": {capital},
  "profil_risque": "{profil_risque}",
  "univers": ["liste des marchés couverts selon la stratégie et la géographie"],
  "poids_max_par_position": 0.07,
  "poids_min_par_position": 0.01,
  "nombre_positions_cible": "25-35",
  "contraintes_sectorielles": {contraintes_sectorielles_json},
  "contraintes_geographiques": {{
    "Amerique_du_Nord": {{"max": 0.65, "min": 0.00}},
    "Europe_developpee": {{"max": 0.50, "min": 0.00}},
    "Asie_Pacifique":   {{"max": 0.30, "min": 0.00}},
    "Marches_emergents": {{"max": 0.20, "min": 0.00}}
  }},
  "actifs_exclus": ["liste des actifs exclus ESG selon la stratégie"],
  "criteres_ESG": {{"score_minimum": "BB"}},
  "limite_turnover": 0.40,
  "cash_min": 0.02,
  "cash_max": 0.10,
  "budget_risque": {{
    "tracking_error_max": {rp['te']},
    "volatilite_max": {rp['vol']},
    "drawdown_max": {dd_max},
    "beta_min": {effective_beta_min},
    "beta_max": {effective_beta_max},
    "concentration_top10_max": {rp['top10']}
  }},
  "frequence_rebalancement": "Trimestriel",
  "liquidite_min_adv_usd": 5000000
}}
"""
        # ── BLOC 6 : Appel LLM ────────────────────────────────────────────────
        raw  = self._call_llm_with_retry(user_msg)
        # Délègue à BaseAgent._call_llm_with_retry :
        #   → pas de tool use pour cet agent (TOOLS = [])
        #   → réponse directe end_turn après la génération du JSON

        data = self._parse_json(raw)
        # Extrait le JSON depuis la réponse brute (retire le markdown éventuel)

        # ── BLOC 7 : Injection des valeurs obligatoires ──────────────────────
        # setdefault : ajoute la clé SEULEMENT si elle est absente du JSON LLM.
        # Protège contre les oublis du LLM (champs non générés).
        data.setdefault("strategie",    strategie)
        data.setdefault("benchmark",    benchmark)
        data.setdefault("horizon",      horizon)
        data.setdefault("capital",      capital)
        data.setdefault("profil_risque", profil_risque)
        data.setdefault("univers", [
            "Actions grandes capitalisations - marchés développés (US, Europe, Japon)",
            "Actions moyennes capitalisations sélectives - marchés développés",
            "Actions émergentes sélectives - jusqu'à 20% du portefeuille",
        ])
        # L'univers ci-dessus est le fallback standard pour "long-only equity global".

        # ── BLOC 8 : Forçage des valeurs source de vérité ───────────────────
        data["capital"]       = capital
        data["profil_risque"] = profil_risque   # Profil réconcilié (beta override si conflit)
        # Force (pas setdefault) : le capital du state est la source de vérité.
        # Le LLM pourrait l'arrondir ou le modifier → on réécrit toujours.

        # Si le gérant a saisi un nombre de positions cible, il fait foi (le LLM
        # mettrait sinon son défaut "25-35"). On le stocke en str (type du champ).
        if nb_positions_cible:
            data["nombre_positions_cible"] = str(int(nb_positions_cible))

        # ── BLOC 9 : Validation Pydantic et retour ────────────────────────────
        mandate = MandateOutput(**data)
        # Pydantic valide chaque champ :
        #   - BudgetRisque utilise ses valeurs par défaut si absent
        #   - ContrainteSectorielle vérifie que max et min sont des floats
        #   - List[str] pour univers et actifs_exclus

        return {
            "mandate":      mandate,
            "current_step": "research",
            # Signale à workflow.py que l'étape suivante est EquityResearchAgent
        }
