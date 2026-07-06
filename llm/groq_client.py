"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  LLM / GROQ CLIENT — Wrapper Groq compatible avec l'interface Anthropic      ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Groq expose un endpoint compatible OpenAI. Ce module utilise donc le SDK   ║
║  OpenAI (`openai` package) avec base_url=https://api.groq.com/openai/v1.    ║
║                                                                              ║
║  L'objectif : que le code BaseAgent qui utilise `client.messages.create()`  ║
║  fonctionne sans modification. Le wrapper traduit les conventions Anthropic ║
║  ↔ OpenAI sous le capot.                                                    ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Différences principales gérées :                                           ║
║                                                                              ║
║  Anthropic                          OpenAI/Groq                              ║
║  ----------                          -----------                             ║
║  system="..." (param top-level)     {"role":"system",...} (1er message)     ║
║  tools=[{name,description,          tools=[{type:"function",function:{      ║
║          input_schema}]                name,description,parameters}}]       ║
║  tool_use block (assistant)         tool_calls (assistant.message)          ║
║  tool_result block (user)           {"role":"tool",content,                 ║
║                                       tool_call_id}                         ║
║  stop_reason: "end_turn"            finish_reason: "stop"                   ║
║  stop_reason: "tool_use"            finish_reason: "tool_calls"             ║
║  block.text                         choice.message.content                  ║
║  ContentBlock(type=...)             .tool_calls / .content                  ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import json
from typing import Any, Dict, List, Optional

# ─────────────────────────────────────────────────────────────────────────────
#  CLASSES MIMANT LES OBJETS DE RÉPONSE ANTHROPIC
#  BaseAgent fait : `for block in response.content: if hasattr(block, "text")...`
#  Donc on a besoin d'objets avec les bons attributs.
# ─────────────────────────────────────────────────────────────────────────────

class _TextBlock:
    """Mime anthropic.types.TextBlock — bloc de texte dans une réponse."""
    type = "text"
    def __init__(self, text: str):
        self.text = text


class _ToolUseBlock:
    """Mime anthropic.types.ToolUseBlock — appel d'outil par le LLM."""
    type = "tool_use"
    def __init__(self, id: str, name: str, input: Dict):
        self.id = id
        self.name = name
        self.input = input


class _Response:
    """Mime anthropic.types.Message — réponse complète du LLM."""
    def __init__(self, content: List, stop_reason: str):
        self.content = content
        self.stop_reason = stop_reason


# ─────────────────────────────────────────────────────────────────────────────
#  TRADUCTEURS DE FORMAT
# ─────────────────────────────────────────────────────────────────────────────

def _tools_anthropic_to_openai(tools: List[Dict]) -> List[Dict]:
    """
    Anthropic : [{name, description, input_schema}]
    OpenAI    : [{type:"function", function:{name, description, parameters}}]
    """
    converted = []
    for t in tools or []:
        converted.append({
            "type": "function",
            "function": {
                "name":        t["name"],
                "description": t.get("description", ""),
                "parameters":  t.get("input_schema", {"type": "object", "properties": {}}),
            },
        })
    return converted


def _messages_anthropic_to_openai(
    system: Optional[str],
    messages: List[Dict],
) -> List[Dict]:
    """
    Convertit l'historique Anthropic en format OpenAI.

    Anthropic messages :
      [{"role":"user","content": "texte"}]
      [{"role":"assistant","content": [TextBlock | ToolUseBlock, ...]}]
      [{"role":"user","content": [{"type":"tool_result","tool_use_id":...,"content":"..."}]}]

    OpenAI messages :
      [{"role":"system","content": "..."}]   (en premier)
      [{"role":"user","content": "texte"}]
      [{"role":"assistant","content": "...", "tool_calls":[{id,type:"function",function:{name,arguments}}]}]
      [{"role":"tool","content": "...","tool_call_id":...}]
    """
    out: List[Dict] = []

    # 1. System prompt en premier message
    if system:
        out.append({"role": "system", "content": system})

    # 2. Conversion message par message
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")

        # ── User message ───────────────────────────────────────────────────────
        if role == "user":
            # Cas simple : content est un string
            if isinstance(content, str):
                out.append({"role": "user", "content": content})
                continue

            # Cas complexe : content est une liste (peut contenir des tool_result)
            if isinstance(content, list):
                # On extrait les tool_results et les transforme en messages "tool"
                text_parts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        tool_msg = {
                            "role":         "tool",
                            "tool_call_id": block.get("tool_use_id"),
                            "content":      block.get("content", ""),
                        }
                        out.append(tool_msg)
                    elif isinstance(block, dict) and block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                    elif isinstance(block, str):
                        text_parts.append(block)
                # Si du texte aussi présent, on l'ajoute comme message user à part
                if text_parts:
                    out.append({"role": "user", "content": "\n".join(text_parts)})
            continue

        # ── Assistant message ──────────────────────────────────────────────────
        if role == "assistant":
            # Cas où content est une string (cas simple)
            if isinstance(content, str):
                out.append({"role": "assistant", "content": content})
                continue

            # Cas où content est une liste de blocs (Anthropic style)
            if isinstance(content, list):
                text_parts = []
                tool_calls = []
                for block in content:
                    # Bloc Anthropic : peut être un objet (TextBlock, ToolUseBlock)
                    # ou un dict (selon comment le code l'a construit).
                    btype = getattr(block, "type", None) or (
                        block.get("type") if isinstance(block, dict) else None
                    )
                    if btype == "text":
                        text = getattr(block, "text", None) or block.get("text", "")
                        text_parts.append(text)
                    elif btype == "tool_use":
                        bid    = getattr(block, "id", None)    or block.get("id")
                        bname  = getattr(block, "name", None)  or block.get("name")
                        binput = getattr(block, "input", None) or block.get("input", {})
                        tool_calls.append({
                            "id":   bid,
                            "type": "function",
                            "function": {
                                "name":      bname,
                                "arguments": json.dumps(binput, ensure_ascii=False),
                            },
                        })

                msg_out = {
                    "role":    "assistant",
                    "content": "\n".join(text_parts) if text_parts else None,
                }
                if tool_calls:
                    msg_out["tool_calls"] = tool_calls
                out.append(msg_out)
            continue

    return out


def _response_openai_to_anthropic(completion) -> _Response:
    """
    Convertit une ChatCompletion OpenAI en _Response style Anthropic.
    """
    choice = completion.choices[0]
    finish = choice.finish_reason  # "stop", "tool_calls", "length", "content_filter"
    msg = choice.message

    content_blocks: List = []

    # Texte de réponse
    if msg.content:
        content_blocks.append(_TextBlock(msg.content))

    # Appels d'outils
    if getattr(msg, "tool_calls", None):
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments) if tc.function.arguments else {}
            except (json.JSONDecodeError, TypeError):
                args = {}
            content_blocks.append(_ToolUseBlock(
                id=tc.id,
                name=tc.function.name,
                input=args,
            ))

    # ── Garde-fou : ne JAMAIS renvoyer un content vide ───────────────────────
    # Les modèles de raisonnement (ex: gpt-oss-20b sur Groq) consomment des tokens
    # de "reasoning" qui comptent dans max_tokens mais n'apparaissent PAS dans
    # msg.content. Si le budget est trop serré, content peut être vide → l'appelant
    # qui fait response.content[0].text plantait ("list index out of range").
    # On garantit au moins un bloc texte pour rester robuste.
    if not content_blocks:
        if finish == "length":
            fallback = ("⚠️ Réponse interrompue (limite de tokens atteinte avant la "
                        "génération de la réponse). Réessayez ou reformulez plus brièvement.")
        else:
            fallback = "⚠️ Réponse vide du modèle. Réessayez."
        content_blocks.append(_TextBlock(fallback))

    # Mapping finish_reason → stop_reason Anthropic
    stop_reason = {
        "stop":           "end_turn",
        "length":         "max_tokens",
        "tool_calls":     "tool_use",
        "content_filter": "end_turn",
    }.get(finish, "end_turn")

    return _Response(content=content_blocks, stop_reason=stop_reason)


# ─────────────────────────────────────────────────────────────────────────────
#  CLASSE PUBLIQUE — INTERFACE PUBLIC IDENTIQUE À anthropic.Anthropic
# ─────────────────────────────────────────────────────────────────────────────

class _MessagesNamespace:
    """Mime `client.messages` côté Anthropic (qui expose .create())."""
    def __init__(self, openai_client, default_model: str):
        self._client = openai_client
        self._default_model = default_model

    def create(
        self,
        model: Optional[str] = None,
        max_tokens: int = 8192,
        system: Optional[str] = None,
        messages: Optional[List[Dict]] = None,
        tools: Optional[List[Dict]] = None,
        **kwargs,
    ) -> _Response:
        """
        Signature identique à anthropic.messages.create().
        Convertit en interne vers le format OpenAI/Groq, appelle, reconvertit.
        """
        openai_messages = _messages_anthropic_to_openai(system, messages or [])

        params: Dict[str, Any] = {
            "model":      model or self._default_model,
            "messages":   openai_messages,
            "max_tokens": max_tokens,
        }
        if tools:
            converted_tools = _tools_anthropic_to_openai(tools)
            # On ne définit tools/tool_choice QUE si la conversion a produit
            # une liste non-vide ET que le modèle peut effectivement les utiliser.
            # Bug observé sur GPT-OSS 20B : envoyer tool_choice="auto" sans tool
            # déclenche "Tool choice is none, but model called a tool".
            if converted_tools:
                params["tools"] = converted_tools
                params["tool_choice"] = "auto"

        completion = self._client.chat.completions.create(**params)
        return _response_openai_to_anthropic(completion)


class GroqAnthropicCompatClient:
    """
    Client Groq exposant la même interface que anthropic.Anthropic.
    Permet à BaseAgent et autres consommateurs de fonctionner sans changement.

    Usage:
        client = GroqAnthropicCompatClient(api_key="gsk_...")
        response = client.messages.create(
            model="llama-3.3-70b-versatile",
            system="Tu es un assistant",
            messages=[{"role":"user","content":"Bonjour"}],
            max_tokens=1024,
        )
        print(response.content[0].text)
    """

    GROQ_BASE_URL = "https://api.groq.com/openai/v1"

    def __init__(
        self,
        api_key: str,
        default_model: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: int = 2,
    ):
        from openai import OpenAI
        # timeout / max_retries portés par le client OpenAI → s'appliquent à TOUS
        # les appels chat.completions.create() sans toucher aux call-sites.
        # Si timeout=None, on laisse le défaut SDK (600s) — mais llm/client.py
        # passe toujours settings.LLM_TIMEOUT.
        client_kwargs: Dict[str, Any] = {
            "api_key":     api_key,
            "base_url":    self.GROQ_BASE_URL,
            "max_retries": max_retries,
        }
        if timeout is not None:
            client_kwargs["timeout"] = timeout
        self._openai = OpenAI(**client_kwargs)
        # default_model n'est utilisé que si l'appelant ne fournit pas de model=
        self.messages = _MessagesNamespace(self._openai, default_model or "llama-3.3-70b-versatile")
