"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  CONFIG / SETTINGS - CONFIGURATION GLOBALE DE L'APPLICATION                 ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Rôle : centraliser tous les paramètres réglables en un seul endroit.      ║
║  Importé très tôt par : base_agent.py, runner.py, workflow.py.             ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  IMPORTS                                                                    │
# └─────────────────────────────────────────────────────────────────────────────┘

import os
# os.getenv : lit les variables d'environnement.
# Utilisé pour récupérer ANTHROPIC_API_KEY et MODEL depuis .env.

from pathlib import Path
# Path(__file__) : chemin absolu vers ce fichier (settings.py)
# Permet d'ancrer la recherche du .env à la racine du projet
# indépendamment du répertoire courant au lancement.

from dotenv import load_dotenv
# python-dotenv : lit le fichier .env à la racine du projet et charge
# chaque ligne "KEY=VALUE" dans os.environ.
# DOIT être appelé AVANT os.getenv() pour que les variables soient disponibles.

load_dotenv(Path(__file__).parent.parent / ".env", override=True)
# Path(__file__).parent.parent : c:\Users\Kylor\alphaswarm\ (racine du projet)
# / ".env" → c:\Users\Kylor\alphaswarm\.env - chemin absolu, indépendant du CWD.
# override=True : force le rechargement même si la variable existe déjà dans l'env
# (évite le cas où ANTHROPIC_API_KEY="" est déjà défini dans l'environnement Windows).


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║  CLASSE SETTINGS                                                            ║
# ║  Conception : attributs de classe (pas d'instance) → constants partagées  ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

class Settings:

    # ┌─────────────────────────────────────────────────────────────────────────┐
    # │  PARAMÈTRE 0 - PROVIDER LLM ACTIF                                      │
    # │  "groq" (gratuit, Llama 3.3 70B) ou "anthropic" (Claude, payant)       │
    # └─────────────────────────────────────────────────────────────────────────┘

    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "groq").lower()
    # Provider par défaut pour TOUS les agents.
    # Surchargeable agent par agent via LLM_PROVIDER_<AGENT> ci-dessous.
    # Permet de basculer en changeant UNE ligne dans .env.

    # ┌─────────────────────────────────────────────────────────────────────────┐
    # │  OVERRIDES PAR AGENT (architecture hybride multi-provider)              │
    # │  Si un agent a un override, il ignore LLM_PROVIDER global.              │
    # │  Utile : Claude pour les agents très exigeants en JSON structuré,       │
    # │          Groq (gratuit) pour le reste.                                  │
    # └─────────────────────────────────────────────────────────────────────────┘

    LLM_PROVIDER_MANDATE:   str = os.getenv("LLM_PROVIDER_MANDATE",   "").lower()
    LLM_PROVIDER_RESEARCH:  str = os.getenv("LLM_PROVIDER_RESEARCH",  "").lower()
    LLM_PROVIDER_PORTFOLIO: str = os.getenv("LLM_PROVIDER_PORTFOLIO", "").lower()
    LLM_PROVIDER_RISK:      str = os.getenv("LLM_PROVIDER_RISK",      "").lower()
    LLM_PROVIDER_EXECUTION: str = os.getenv("LLM_PROVIDER_EXECUTION", "").lower()
    LLM_PROVIDER_CHAT:      str = os.getenv("LLM_PROVIDER_CHAT",      "").lower()

    # Modèles par provider - utilisés quand un agent override le provider global.
    # MODEL reste pour le provider GLOBAL ; ces deux-là pour les overrides.
    MODEL_ANTHROPIC: str = os.getenv("MODEL_ANTHROPIC", "claude-sonnet-4-6")
    MODEL_GROQ:      str = os.getenv("MODEL_GROQ",      "openai/gpt-oss-20b")

    # ┌─────────────────────────────────────────────────────────────────────────┐
    # │  PARAMÈTRE 1 - CLÉS API                                                │
    # │  Une clé par provider. Seule celle du provider actif est obligatoire. │
    # └─────────────────────────────────────────────────────────────────────────┘

    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    # Clé Anthropic (Claude). Obligatoire si LLM_PROVIDER=anthropic.

    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    # Clé Groq (Llama, Qwen). Obligatoire si LLM_PROVIDER=groq.
    # Inscription gratuite sur console.groq.com.

    # ┌─────────────────────────────────────────────────────────────────────────┐
    # │  PARAMÈTRE 2 - MODÈLE                                                  │
    # │  Le nom du modèle dépend du provider actif.                            │
    # └─────────────────────────────────────────────────────────────────────────┘

    MODEL: str = os.getenv("MODEL", "qwen/qwen3-32b")
    # Provider groq      → qwen/qwen3-32b (recommandé tool use), llama-3.3-70b-versatile,
    #                      openai/gpt-oss-20b
    # Provider anthropic → claude-sonnet-4-6, claude-opus-4-6

    # ┌─────────────────────────────────────────────────────────────────────────┐
    # │  PARAMÈTRE 3 - LIMITE DE TOKENS DE SORTIE                             │
    # └─────────────────────────────────────────────────────────────────────────┘

    MAX_TOKENS: int = 4000
    # Maximum de tokens en sortie. Largement suffisant pour les JSON des agents
    # (mandat ~2K tokens, portfolio ~3K, research ~3K, risk ~2K, execution ~2K).
    # Réduit à 4K (depuis 8K) pour rester compatible avec les TPM limites Groq
    # tier gratuit (6-12K tokens/min selon modèle). Sur Anthropic, aucun impact :
    # le modèle ne génère que ce qu'il a à dire, max_tokens est juste un plafond.

    # ┌─────────────────────────────────────────────────────────────────────────┐
    # │  PARAMÈTRE 3b - TIMEOUT DES APPELS LLM (secondes)                       │
    # └─────────────────────────────────────────────────────────────────────────┘

    LLM_TIMEOUT: int = int(os.getenv("LLM_TIMEOUT", "120"))
    # Délai max d'UN appel LLM avant abandon (TimeoutError côté SDK).
    # Porté au CONSTRUCTEUR du client (llm/client.py) → couvre tous les call-sites
    # (boucle BaseAgent, appel forcé "15 outils", endpoints chat de api.py).
    # Sans ce timeout, le défaut SDK est 600s (10 min) : un provider qui ne répond
    # jamais fait pendre le thread du workflow. 120s = large pour un appel normal
    # (5-60s) tout en évitant les hangs. Les erreurs de timeout sont retentées par
    # _call_llm_with_retry (cf. base_agent.py).

    # ┌─────────────────────────────────────────────────────────────────────────┐
    # │  PARAMÈTRE 4 - BOUCLE RISK ↔ PORTFOLIO                                │
    # └─────────────────────────────────────────────────────────────────────────┘

    MAX_PORTFOLIO_ITERATIONS: int = 3
    # Nombre maximum de fois que PortfolioConstructionAgent peut être relancé
    # après un statut AJUSTER du RiskManagementAgent.
    # 3 itérations = bon compromis : assez pour corriger, pas trop pour éviter
    # les timeouts. Chaque itération = ~30-45s de latence LLM.

    # ┌─────────────────────────────────────────────────────────────────────────┐
    # │  PARAMÈTRES 5-6 - DOSSIERS DE SORTIE                                  │
    # └─────────────────────────────────────────────────────────────────────────┘

    FMP_API_KEY: str = os.getenv("FMP_API_KEY", "")

    TAVILY_API_KEY: str = os.getenv("TAVILY_API_KEY", "")
    # Clé API Tavily (tavily.com) - moteur de recherche conçu pour agents IA.
    # Free tier : 1 000 recherches/mois.
    # Utilisée par tools/web_search.py pour les actualités et vues analystes.
    # Si vide → web_search.py retourne {"statut": "SKIP"} sans erreur.
    # Clé API Financial Modeling Prep (financialmodelingprep.com).
    # Free tier : 250 appels/jour, 10 appels/minute.
    # Utilisée par tools/fmp_data.py pour les données historiques 10 ans.
    # Si vide → fmp_data.py retourne {"statut": "SKIP"} sans erreur.

    # Racine du projet, résolue depuis ce fichier : les dossiers de sortie ne
    # dépendent plus du répertoire courant au lancement (C12).
    _ROOT = Path(__file__).resolve().parent.parent

    EXPORTS_DIR: str = str(_ROOT / os.getenv("EXPORTS_DIR", "exports"))
    # Répertoire des fichiers d'ordres JSON pour l'OMS.
    # Ex: exports/orders_57234B42.json
    # Créé automatiquement par runner.py si absent.

    OUTPUTS_DIR: str = str(_ROOT / os.getenv("OUTPUTS_DIR", "outputs"))
    # Répertoire des runs complets (état final de tous les agents) et rapports HTML.
    # Ex: outputs/run_57234B42.json
    #     outputs/research/NVDA_report_20260322.html
    # Créé automatiquement par runner.py si absent.

    # ┌─────────────────────────────────────────────────────────────────────────┐
    # │  MÉTHODE validate() - VÉRIFICATION AVANT DÉMARRAGE                    │
    # │  Appelée en tout premier dans runner.py (avant les agents).            │
    # └─────────────────────────────────────────────────────────────────────────┘

    @classmethod  # Méthode de classe : accède à cls (Settings) sans instance
    def validate(cls) -> None:
        # ── Liste de tous les providers utilisés (global + overrides) ─────────
        providers_used = {cls.LLM_PROVIDER}
        for ov in (
            cls.LLM_PROVIDER_MANDATE,
            cls.LLM_PROVIDER_RESEARCH,
            cls.LLM_PROVIDER_PORTFOLIO,
            cls.LLM_PROVIDER_RISK,
            cls.LLM_PROVIDER_EXECUTION,
            cls.LLM_PROVIDER_CHAT,
        ):
            if ov:
                providers_used.add(ov)

        # ── Validation : chaque provider utilisé doit avoir sa clé ────────────
        for p in providers_used:
            if p == "anthropic":
                if not cls.ANTHROPIC_API_KEY:
                    raise ValueError(
                        "ANTHROPIC_API_KEY manquant. Au moins un agent utilise Anthropic. "
                        "Renseigne la clé dans .env."
                    )
            elif p == "groq":
                if not cls.GROQ_API_KEY:
                    raise ValueError(
                        "GROQ_API_KEY manquant. Au moins un agent utilise Groq. "
                        "Crée une clé gratuite sur https://console.groq.com."
                    )
            else:
                raise ValueError(
                    f"Provider '{p}' inconnu. Valeurs supportées : 'groq', 'anthropic'."
                )

    # ┌─────────────────────────────────────────────────────────────────────────┐
    # │  HELPERS : résoudre le provider et le modèle pour un agent donné       │
    # │  Utilisés par BaseAgent.__init__ pour choisir le bon client.           │
    # └─────────────────────────────────────────────────────────────────────────┘

    @classmethod
    def resolve_provider(cls, agent_key: str) -> str:
        """Retourne le provider pour un agent donné (override ou défaut global)."""
        override_attr = f"LLM_PROVIDER_{agent_key.upper()}"
        override_val = getattr(cls, override_attr, "") or ""
        return override_val or cls.LLM_PROVIDER

    @classmethod
    def resolve_model(cls, agent_key: str) -> str:
        """
        Retourne le nom de modèle adapté au provider actif pour cet agent.
        - Si l'agent override le provider, utilise MODEL_ANTHROPIC ou MODEL_GROQ.
        - Sinon, utilise MODEL (le modèle global).
        """
        provider = cls.resolve_provider(agent_key)
        # Si pas d'override, le provider est le global → utiliser le MODEL global
        override_attr = f"LLM_PROVIDER_{agent_key.upper()}"
        if not (getattr(cls, override_attr, "") or ""):
            return cls.MODEL
        # Sinon, utiliser le modèle dédié au provider override
        if provider == "anthropic":
            return cls.MODEL_ANTHROPIC
        if provider == "groq":
            return cls.MODEL_GROQ
        return cls.MODEL


# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  SINGLETON settings                                                         │
# │  Importé partout via : from config.settings import settings                │
# └─────────────────────────────────────────────────────────────────────────────┘

settings = Settings()
# On crée une instance unique dès l'import du module.
# Comme les attributs sont des attributs de CLASSE, settings et Settings
# donnent accès aux mêmes valeurs (settings.MODEL == Settings.MODEL).
# La convention "settings" minuscule est plus lisible dans les agents.
