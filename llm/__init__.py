"""
Couche d'abstraction provider LLM.
Permet de basculer entre Anthropic (Claude) et Groq (Llama) via .env.
Voir llm/client.py pour le point d'entrée.
"""

from .client import get_client

__all__ = ["get_client"]
