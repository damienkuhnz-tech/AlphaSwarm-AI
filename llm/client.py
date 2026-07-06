"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  LLM / CLIENT — FACTORY PROVIDER-AGNOSTIQUE                                 ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Rôle : exposer une interface unique compatible avec le SDK Anthropic       ║
║  pour permettre aux agents d'appeler indifféremment Claude ou Llama (Groq). ║
║                                                                              ║
║  Le code existant utilise `client.messages.create(...)`. On garde cette     ║
║  signature pour ne rien casser : le wrapper Groq traduit en interne vers    ║
║  l'API OpenAI-like (Groq utilise un endpoint compatible OpenAI).            ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

from typing import Optional

from config.settings import settings


def get_client(provider: Optional[str] = None):
    """
    Retourne un client LLM compatible avec l'interface Anthropic.

    Args:
        provider: nom du provider à forcer ("anthropic" ou "groq").
                  Si None, utilise settings.LLM_PROVIDER (défaut global).
                  Permet à BaseAgent de demander un client spécifique pour un
                  agent qui override le provider via LLM_PROVIDER_<AGENT>.

    Tous les clients exposent : `client.messages.create(...)`.
    Tous les retours exposent : `response.content` (liste de blocs),
                                `response.stop_reason` (str).
    """
    p = (provider or settings.LLM_PROVIDER).lower()

    if p == "anthropic":
        import anthropic
        # timeout + max_retries portés par le client → couvrent tous les call-sites
        # (boucle BaseAgent, appel forcé "15 outils", endpoints chat de api.py).
        return anthropic.Anthropic(
            api_key=settings.ANTHROPIC_API_KEY,
            timeout=settings.LLM_TIMEOUT,
            max_retries=2,
        )

    if p == "groq":
        from .groq_client import GroqAnthropicCompatClient
        return GroqAnthropicCompatClient(
            api_key=settings.GROQ_API_KEY,
            timeout=settings.LLM_TIMEOUT,
            max_retries=2,
        )

    raise ValueError(
        f"Provider='{p}' inconnu. Valeurs supportées : 'groq', 'anthropic'."
    )


# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  get_retryable_exceptions() — TYPES D'EXCEPTIONS RETENTABLES PAR PROVIDER   │
# │  Utilisé par BaseAgent._call_llm_with_retry pour être indépendant du        │
# │  provider : selon LLM_PROVIDER, les appels lèvent des exceptions anthropic.* │
# │  OU openai.* (Groq passe par le SDK openai). On agrège les deux familles    │
# │  quand les SDK sont installés.                                              │
# └─────────────────────────────────────────────────────────────────────────────┘

def get_retryable_exceptions():
    """
    Retourne (network_excs, status_excs) :
      - network_excs : tuple de types d'exceptions « réseau » (connexion/timeout)
                       → à retenter avec backoff court.
      - status_excs  : tuple de types d'exceptions « statut HTTP » (porteuses d'un
                       .status_code) → l'appelant inspecte le code (429/5xx → retry,
                       4xx → abandon).

    Importe anthropic ET openai en try/except : si un SDK n'est pas installé,
    il est simplement absent du tuple (jamais d'ImportError fatal).
    """
    network_excs: tuple = ()
    status_excs: tuple = ()

    try:
        import anthropic
        network_excs += (anthropic.APIConnectionError, anthropic.APITimeoutError)
        status_excs  += (anthropic.APIStatusError,)
    except ImportError:
        pass

    try:
        import openai
        network_excs += (openai.APIConnectionError, openai.APITimeoutError)
        # openai.RateLimitError et openai.APIStatusError portent tous deux
        # .status_code ; APIStatusError couvre 4xx/5xx, RateLimitError le 429.
        status_excs  += (openai.APIStatusError,)
    except ImportError:
        pass

    return network_excs, status_excs
