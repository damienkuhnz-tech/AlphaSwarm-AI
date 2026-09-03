"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  AGENTS / BASE AGENT - CLASSE MÈRE DE TOUS LES AGENTS                       ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Rôle : factoriser la logique commune à tous les agents.                    ║
║  Tout agent hérite de BaseAgent et n'implémente que run().                  ║
║  Le reste (appel LLM, retry, outils, parsing JSON) est géré ici.           ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  IMPORTS STANDARDS                                                          │
# └─────────────────────────────────────────────────────────────────────────────┘

import json   # Sérialise les résultats d'outils (dict → str JSON) avant de les
              # renvoyer au LLM. Aussi utilisé pour parser la réponse finale.

import time   # Utilisé uniquement dans _call_llm_with_retry pour les délais
              # entre tentatives en cas d'erreur réseau (5s, 10s, 15s).

from abc import ABC, abstractmethod
# ABC            : rend BaseAgent non-instanciable directement.
# abstractmethod : force chaque sous-classe à implémenter run().
# Si un agent oublie run(), Python lève TypeError à l'instanciation.

from typing import Any, Dict, List, Optional
# Any      : type de retour générique pour _execute_tool (dict, str, int...)
# Dict     : type des messages API et des résultats d'outils
# List     : type des outils TOOLS et des messages
# Optional : client peut être None (on en crée un si absent)

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  IMPORTS INTERNES                                                           │
# └─────────────────────────────────────────────────────────────────────────────┘

from config.settings import settings
# Fournit : settings.MODEL, settings.MAX_TOKENS, settings.LLM_PROVIDER
# Centralisé dans config/settings.py pour ne changer qu'à un seul endroit.

from llm.client import get_client, get_retryable_exceptions
# Factory provider-agnostique : retourne un client Anthropic OU Groq selon
# LLM_PROVIDER dans .env. L'objet retourné expose la même API que anthropic.Anthropic.
# get_retryable_exceptions : agrège les types d'exceptions réseau/statut des deux
# SDK (anthropic + openai) → _call_llm_with_retry est indépendant du provider.

from models.state import PortfolioState
# Type du dict partagé entre tous les agents.
# Utilisé uniquement pour l'annotation de type de run().

# ── Types d'exceptions retentables, résolus UNE FOIS à l'import ────────────────
# _NETWORK_EXCS : erreurs de connexion/timeout (backoff court).
# _STATUS_EXCS  : erreurs porteuses d'un .status_code (on inspecte le code :
#                 429/529/5xx → retry, 4xx → abandon).
# Si un SDK est absent, son tuple est simplement vide ("except ()" ne matche rien).
_NETWORK_EXCS, _STATUS_EXCS = get_retryable_exceptions()


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║  CLASSE BASEAGENT                                                           ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

class BaseAgent(ABC):
    """Classe abstraite - ne peut pas être instanciée directement."""

    # ┌─────────────────────────────────────────────────────────────────────────┐
    # │  ATTRIBUTS DE CLASSE (définis au niveau de la classe, pas de l'instance)│
    # └─────────────────────────────────────────────────────────────────────────┘

    SYSTEM_PROMPT: str = ""
    # Chaque agent override cette variable avec son propre prompt.

    TOOLS: List[Dict] = []
    # Liste des outils que le LLM peut appeler.

    AGENT_KEY: str = ""
    # Clé identifiant l'agent pour les overrides de provider dans .env.
    # Valeurs : "mandate", "research", "portfolio", "risk", "execution", "chat".
    # Utilisée par __init__ pour choisir le bon client (Claude vs Groq).
    # Si vide → utilise LLM_PROVIDER global.

    # ┌─────────────────────────────────────────────────────────────────────────┐
    # │  CONSTRUCTEUR __init__                                                  │
    # │  Appelé quand WorkflowEngine instancie chaque agent (workflow.py)       │
    # └─────────────────────────────────────────────────────────────────────────┘

    def __init__(self, client=None):

        # ── Résolution du provider et du modèle pour cet agent ────────────────
        # Si l'agent a une AGENT_KEY (ex: "mandate"), on regarde dans .env
        # s'il y a un override LLM_PROVIDER_MANDATE. Sinon → provider global.
        if self.AGENT_KEY:
            agent_provider = settings.resolve_provider(self.AGENT_KEY)
            agent_model    = settings.resolve_model(self.AGENT_KEY)
        else:
            agent_provider = settings.LLM_PROVIDER
            agent_model    = settings.MODEL

        # ── Injection du client ───────────────────────────────────────────────
        # Si l'appelant fournit un client (ex: workflow.py partage UN client global),
        # on l'utilise - sauf si l'agent a un provider override différent du global,
        # auquel cas on en crée un dédié pour respecter l'override.
        if client and agent_provider == settings.LLM_PROVIDER:
            self.client = client
        else:
            self.client = get_client(provider=agent_provider)

        # ── Provider résolu (mémorisé) ────────────────────────────────────────
        # Sert de garde pour le prompt caching dans _call_llm : on n'envoie le
        # bloc cache_control (spécifique Anthropic) que si provider == "anthropic".
        # Pour Groq (SDK openai), le system reste une string brute (no-op strict).
        self.provider   = agent_provider

        # ── Modèle et tokens ──────────────────────────────────────────────────
        self.model      = agent_model
        # MAX_TOKENS_OVERRIDE : constante de classe optionnelle. Permet à un agent
        # qui produit un gros JSON (ex: PortfolioConstructionAgent, ~45 positions)
        # d'élargir SON budget de sortie sans pénaliser les autres agents ni frôler
        # les limites TPM Groq (free tier) sur tous les appels.
        self.max_tokens = getattr(self, "MAX_TOKENS_OVERRIDE", None) or settings.MAX_TOKENS

    # ┌─────────────────────────────────────────────────────────────────────────┐
    # │  MÉTHODE ABSTRAITE run()                                                │
    # │  Chaque agent DOIT implémenter cette méthode.                           │
    # │  Contrat : reçoit l'état global → retourne un dict de mises à jour.    │
    # └─────────────────────────────────────────────────────────────────────────┘

    @abstractmethod
    def run(self, state: PortfolioState) -> Dict[str, Any]:
        # state  : l'état complet du workflow (toutes les clés accumulées)
        # retour : dict partiel avec les nouvelles clés à merger dans state
        # Ex: {"mandate": mandate_obj, "current_step": "idea_generation"}
        pass

    # ┌─────────────────────────────────────────────────────────────────────────┐
    # │  _call_llm() - BOUCLE PRINCIPALE D'APPEL AU LLM                        │
    # │  Gère : appel initial → tool use → réponse finale                      │
    # │  C'est le cœur de BaseAgent. Tous les agents passent par ici.          │
    # └─────────────────────────────────────────────────────────────────────────┘

    def _call_llm(
        self,
        user_message: str,        # Le message à envoyer au LLM (prompt utilisateur)
        tools: Optional[List[Dict]] = None,  # Override des outils (sinon self.TOOLS)
    ) -> str:                     # Retourne le texte final généré par le LLM

        # ── Initialisation de l'historique de messages ────────────────────────
        # L'API Anthropic attend une liste de messages alternés user/assistant.
        # On démarre avec UN seul message utilisateur.
        messages = [{"role": "user", "content": user_message}]

        # ── Choix des outils actifs ───────────────────────────────────────────
        # Si l'appelant passe des outils spécifiques → on les utilise.
        # Sinon → on prend ceux de la classe (self.TOOLS).
        active_tools = tools or self.TOOLS

        # ── Compteurs de sécurité ─────────────────────────────────────────────
        max_tool_calls  = 15  # Jamais plus de 15 appels d'outils par agent
        tool_call_count = 0   # Compteur incrémenté à chaque outil exécuté
        # Raison du garde-fou : sans limite, un LLM "curieux" peut appeler
        # get_stock_info 30 fois → timeout ou coût excessif.

        # ── Budget de tokens effectif (thread-safe) ───────────────────────────
        # Variable LOCALE (pas self.max_tokens) car le Research Agent appelle
        # _call_llm depuis un ThreadPoolExecutor → muter self casserait les
        # autres threads. Si la réponse est tronquée (stop_reason="max_tokens"),
        # on relance UNE fois avec ce budget doublé.
        effective_max_tokens = self.max_tokens
        truncation_retried    = False

        # ── Boucle principale ─────────────────────────────────────────────────
        # Cette boucle tourne jusqu'à ce que :
        #   a) Le LLM termine sa réponse (end_turn ou max_tokens)
        #   b) Le garde-fou de 15 outils est atteint
        #   c) Un stop_reason inattendu arrive (break)
        while True:

            # ── Prompt caching (Anthropic uniquement) ─────────────────────────
            # Le system prompt est identique sur les ~15 appels d'un run research.
            # En l'envoyant comme bloc avec cache_control "ephemeral", Anthropic le
            # met en cache : lectures ~0,1× le coût + TTFT réduit sur les appels
            # suivants. Pour Groq (SDK openai), cache_control n'est pas supporté →
            # on garde la string brute (no-op strict, aucune régression).
            if self.provider == "anthropic":
                system_field: Any = [{
                    "type":          "text",
                    "text":          self.SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }]
            else:
                system_field = self.SYSTEM_PROMPT

            # ── Assemblage du payload API ─────────────────────────────────────
            # L'API Anthropic attend un dict avec au minimum model/max_tokens/messages.
            # system est passé séparément (pas dans messages) pour l'API Anthropic.
            kwargs: Dict[str, Any] = {
                "model":      self.model,            # "claude-sonnet-4-6"
                "max_tokens": effective_max_tokens,  # budget courant (doublé si retry)
                "system":     system_field,          # string (Groq) ou bloc caché (Anthropic)
                "messages":   messages,              # Historique de la conversation
            }

            # N'ajoute "tools" que si la liste n'est pas vide.
            # L'API rejette tools=[] → on l'omet complètement si pas d'outils.
            if active_tools:
                kwargs["tools"] = active_tools

            # ── Appel HTTP à l'API Anthropic ──────────────────────────────────
            # Bloquant (synchrone). Peut prendre 5-60s selon la complexité.
            response = self.client.messages.create(**kwargs)

            # ═════════════════════════════════════════════════════════════════
            # CAS 1 : Le LLM a terminé sa réponse (stop_reason = "end_turn")
            # ═════════════════════════════════════════════════════════════════
            if response.stop_reason == "end_turn":
                # response.content est une liste de blocs (TextBlock, ToolUseBlock...)
                # On cherche le premier bloc avec du texte.
                for block in response.content:
                    if hasattr(block, "text"):
                        return block.text  # ← Sortie normale de la fonction
                return ""  # ← Aucun bloc texte trouvé (rare)

            # ═════════════════════════════════════════════════════════════════
            # CAS 1bis : Réponse TRONQUÉE (stop_reason = "max_tokens")
            #   Le LLM a buté sur le plafond de tokens → le JSON est incomplet.
            #   AVANT : on retournait ce texte tronqué → _parse_json crashait
            #   ("Unterminated string"). MAINTENANT : on relance UNE fois avec le
            #   budget doublé. Si ça tronque encore, on retourne le meilleur texte
            #   disponible et on laisse _parse_json tenter une réparation.
            # ═════════════════════════════════════════════════════════════════
            if response.stop_reason == "max_tokens":
                partial_text = ""
                for block in response.content:
                    if hasattr(block, "text"):
                        partial_text = block.text
                        break
                if not truncation_retried:
                    truncation_retried   = True
                    effective_max_tokens = min(effective_max_tokens * 2, 16000)
                    # Relance le MÊME message (pas d'ajout à l'historique) avec
                    # un budget plus large. continue → nouvelle itération de boucle.
                    continue
                # Déjà retenté une fois : on rend le texte le plus complet obtenu.
                return partial_text

            # ═════════════════════════════════════════════════════════════════
            # CAS 2 : Le LLM veut utiliser un outil (stop_reason = "tool_use")
            #         Il a identifié qu'il a besoin de données externes.
            # ═════════════════════════════════════════════════════════════════
            if response.stop_reason == "tool_use":

                # ── Exécution de chaque outil demandé ────────────────────────
                tool_results = []  # Accumulera les résultats pour les renvoyer au LLM
                for block in response.content:
                    if block.type == "tool_use":
                        tool_call_count += 1  # Incrémente le compteur de sécurité

                        # Exécute l'outil Python correspondant au nom demandé
                        # block.name  : ex "get_stock_info"
                        # block.input : ex {"ticker": "NVDA"}
                        result = self._execute_tool(block.name, block.input)

                        # Formate le résultat selon le protocole de l'API Anthropic.
                        # "tool_use_id" doit correspondre exactement au block.id
                        # pour que l'API sache à quel appel correspond ce résultat.
                        tool_results.append({
                            "type":        "tool_result",
                            "tool_use_id": block.id,
                            "content":     json.dumps(result, ensure_ascii=False),
                            # json.dumps : convertit le dict Python en string JSON
                            # ensure_ascii=False : garde les accents et caractères UTF-8
                        })

                # ── Mise à jour de l'historique ───────────────────────────────
                # On ajoute DEUX nouveaux messages à l'historique :
                #   1. La réponse assistant (avec les tool_use blocks)
                #   2. Les résultats des outils (rôle "user" par convention API)
                # Pourquoi "+=" avec une nouvelle liste ? Pour garder l'immuabilité
                # (évite les bugs de mutation si messages était partagé).
                messages = messages + [
                    {"role": "assistant", "content": response.content},
                    {"role": "user",      "content": tool_results},
                ]

                # ── Garde-fou : trop d'appels d'outils ───────────────────────
                if tool_call_count >= max_tool_calls:
                    # On force le LLM à conclure avec les données déjà reçues.
                    # Sans ce garde-fou, la boucle pourrait tourner indéfiniment.
                    force_msg = messages + [{
                        "role":    "user",
                        "content": "Retourne maintenant le JSON final avec les donnees deja collectees.",
                    }]
                    # Appel final sans outils pour forcer la conclusion
                    final = self.client.messages.create(
                        model=self.model,
                        max_tokens=self.max_tokens,
                        system=self.SYSTEM_PROMPT,
                        messages=force_msg,
                        # Note : pas de "tools" → le LLM ne peut plus appeler d'outils
                    )
                    for block in final.content:
                        if hasattr(block, "text"):
                            return block.text
                    return ""

                # Relance la boucle pour que le LLM traite les résultats d'outils
                continue

            # ═════════════════════════════════════════════════════════════════
            # CAS 3 : stop_reason inattendu (ne devrait pas arriver)
            # ═════════════════════════════════════════════════════════════════
            break  # Sort de la boucle proprement sans crasher

        return ""  # Retour de secours (atteint uniquement après le break)

    # ┌─────────────────────────────────────────────────────────────────────────┐
    # │  _call_llm_with_retry() - WRAPPER AVEC RETRY RÉSEAU                    │
    # │  Relance automatiquement _call_llm en cas d'erreur réseau temporaire.  │
    # └─────────────────────────────────────────────────────────────────────────┘

    def _call_llm_with_retry(
        self,
        user_message: str,
        tools: Optional[List[Dict]] = None,
        max_retries: int = 3,      # Nombre maximum de tentatives réseau normales
    ) -> str:
        # ── Provider-agnostique ───────────────────────────────────────────────
        # Le provider par défaut est Groq (SDK openai) ; Anthropic est l'alternative.
        # Les exceptions retentables (_NETWORK_EXCS / _STATUS_EXCS) agrègent les deux
        # familles (cf. llm.client.get_retryable_exceptions), donc cette méthode
        # gère indifféremment Claude et Groq. AVANT, seules les exceptions
        # anthropic.* étaient attrapées → aucun retry ni gestion du 429 sur Groq.

        # ── Compteurs ─────────────────────────────────────────────────────────
        # max_throttle_retries : 429 (rate limit) / 529 / 5xx ont leur propre quota,
        #   indépendant des retries réseau normaux (le free tier Groq déclenche des
        #   429 en rafale qu'il faut absorber sans consommer les tentatives réseau).
        # attempt : compteur manuel (while) pour les erreurs réseau classiques.
        #   Ne peut PAS être un for/range : on doit pouvoir annuler l'incrément lors
        #   d'un throttle (attempt -= 1 est effectif dans while, pas dans for).
        max_throttle_retries = 8
        attempt_throttle = 0
        attempt = 0  # compteur manuel d'erreurs réseau

        while attempt < max_retries:
            attempt += 1  # Incrément en début de boucle → annulable via attempt -= 1
            try:
                raw = self._call_llm(user_message, tools)
                # Si on obtient une réponse non vide → succès, on retourne
                if raw and raw.strip():
                    return raw
                # Si réponse vide → on continue la boucle (retry)

            except _STATUS_EXCS as e:
                # ── Erreur HTTP porteuse d'un status_code ─────────────────────
                # 429 = rate limit (Groq free tier), 529 = surcharge Anthropic,
                # 5xx = erreur serveur transitoire → on attend et on retente SANS
                # consommer une tentative "réseau" (attempt -= 1 annule l'incrément).
                status = getattr(e, "status_code", None)
                transient = (
                    status == 429
                    or status == 529
                    or (isinstance(status, int) and status >= 500)
                )
                if transient:
                    attempt_throttle += 1
                    if attempt_throttle > max_throttle_retries:
                        raise  # Quota throttle épuisé → on abandonne
                    # Respecte l'en-tête Retry-After si présent, sinon backoff
                    # linéaire plafonné à 60s : 15s, 30s, 45s, 60s, 60s...
                    wait = self._retry_after_seconds(e) or min(15 * attempt_throttle, 60)
                    print(
                        f"[retry] LLM indisponible (HTTP {status}) - attente {wait:.0f}s "
                        f"(essai {attempt_throttle}/{max_throttle_retries})",
                        flush=True,
                    )
                    time.sleep(wait)
                    attempt -= 1  # Annule l'incrément - EFFECTIF dans un while
                    continue
                # Erreurs client 4xx (400, 401, 403...) → inutile de retenter
                # (clé invalide, requête malformée : ça ne changera pas).
                raise

            except _NETWORK_EXCS:
                # ── Erreur réseau : on retente après délai croissant ──────────
                # APIConnectionError : pas de réseau, DNS échoué, SSL error
                # APITimeoutError    : le serveur met trop de temps (timeout client)
                if attempt == max_retries:
                    raise  # À la dernière tentative, on laisse l'exception remonter
                wait = 5 * attempt  # Délai : 5s → 10s → 15s (backoff linéaire)
                time.sleep(wait)

        return ""  # Retour de secours si toutes les tentatives retournent vide

    # ┌─────────────────────────────────────────────────────────────────────────┐
    # │  _retry_after_seconds() - LIT L'EN-TÊTE Retry-After D'UNE ERREUR HTTP   │
    # └─────────────────────────────────────────────────────────────────────────┘

    @staticmethod
    def _retry_after_seconds(exc) -> Optional[float]:
        """
        Extrait le délai d'attente conseillé par le serveur (en-tête Retry-After),
        plafonné à 60s. Retourne None si absent/illisible → l'appelant utilise son
        backoff par défaut. Les exceptions des SDK anthropic/openai exposent .response
        (httpx.Response) porteuse des en-têtes.
        """
        try:
            resp = getattr(exc, "response", None)
            if resp is not None:
                ra = resp.headers.get("retry-after")
                if ra:
                    return min(float(ra), 60)
        except (ValueError, AttributeError, TypeError):
            pass
        return None

    # ┌─────────────────────────────────────────────────────────────────────────┐
    # │  _execute_tool() - DISPATCH DES OUTILS                                 │
    # │  Relie le nom d'outil (string retourné par le LLM) à la fonction Python│
    # └─────────────────────────────────────────────────────────────────────────┘

    def _execute_tool(self, tool_name: str, tool_input: Dict) -> Any:
        # ── Imports retardés (lazy imports) ──────────────────────────────────
        # On importe ici (pas en haut du fichier) pour deux raisons :
        #   1. Évite les imports circulaires (tools → agents → tools)
        #   2. Ces imports ne coûtent que si un outil est vraiment appelé
        from tools.market_data       import get_stock_info, get_financials, get_price_history
        from tools.financial_metrics import compute_portfolio_metrics

        # ── Table de dispatch ─────────────────────────────────────────────────
        # Associe chaque nom d'outil (string) à une lambda qui appelle la fonction.
        # Les lambdas extraient les paramètres depuis tool_input (dict fourni par le LLM).
        dispatch = {
            "get_stock_info":   lambda i: get_stock_info(i["ticker"]),
            # i["ticker"] : le LLM a rempli ce champ selon le schéma de l'outil

            "get_financials":   lambda i: get_financials(i["ticker"]),

            "get_price_history": lambda i: get_price_history(
                i["ticker"],
                i.get("period", "1y")  # "period" est optionnel → défaut "1y"
            ),

            "compute_portfolio_metrics": lambda i: compute_portfolio_metrics(
                i["positions"],          # Liste de {"ticker": ..., "poids": ...}
                i.get("period", "1y")    # Période d'historique pour les calculs
            ),
        }

        fn = dispatch.get(tool_name)
        # ── Exécution ou erreur contrôlée ─────────────────────────────────────
        # Si le LLM demande un outil inconnu → retourne un dict d'erreur (pas d'exception).
        # L'agent peut continuer sans crasher, avec des données partielles.
        return fn(tool_input) if fn else {"erreur": f"Tool inconnu: {tool_name}"}

    # ┌─────────────────────────────────────────────────────────────────────────┐
    # │  _parse_json() - EXTRACTION ROBUSTE DU JSON DEPUIS LA RÉPONSE LLM      │
    # │  Le LLM peut entourer le JSON de texte, markdown, explications, etc.   │
    # │  Cette méthode extrait le JSON pur même dans ces cas.                  │
    # └─────────────────────────────────────────────────────────────────────────┘

    @staticmethod  # Pas besoin de self → méthode utilitaire pure
    def _parse_json(text: str) -> Dict:

        # ── Garde : réponse vide ──────────────────────────────────────────────
        # Si le LLM retourne "" ou None (problème réseau, max_tokens trop bas...)
        if not text or not text.strip():
            raise ValueError("Reponse LLM vide. Relance python main.py")

        original = text  # Garde la version originale pour les messages d'erreur
        text = text.strip()  # Supprime les espaces et retours ligne en début/fin

        # ── Stratégie 1 : bloc markdown ```json ... ``` ───────────────────────
        # Le LLM retourne souvent : "Voici le JSON :\n```json\n{...}\n```"
        if "```json" in text:
            text = text.split("```json")[1]  # Prend ce qui est après ```json
            text = text.split("```")[0]      # Prend ce qui est avant le ``` fermant
            text = text.strip()

        # ── Stratégie 2 : bloc markdown ``` ... ``` (sans "json") ─────────────
        elif "```" in text:
            text = text.split("```")[1]  # Premier bloc de code
            text = text.split("```")[0]
            text = text.strip()

        # ── Stratégie 3 : recherche du premier { ou [ dans le texte ──────────
        # Le LLM peut écrire du texte avant le JSON : "Voici mon analyse : {...}"
        else:
            for sc, ec in [('{', '}'), ('[', ']')]:
                # sc = caractère ouvrant ({ ou [)
                # ec = caractère fermant (} ou ])
                s = text.find(sc)    # Position du premier caractère ouvrant
                if s != -1:
                    e = text.rfind(ec)  # Position du DERNIER caractère fermant
                    if e > s:           # Vérifie qu'on a bien un bloc valide
                        text = text[s:e + 1]  # Extrait le JSON
                        break

        # ── Parsing JSON ──────────────────────────────────────────────────────
        try:
            return json.loads(text)  # Convertit la string JSON en dict Python
        except json.JSONDecodeError as e:
            # ── Filet de sécurité : tentative de réparation d'un JSON tronqué ──
            # Malgré le retry sur max_tokens (cf. _call_llm), une réponse peut
            # rester coupée. Plutôt que de crasher l'agent, on tente de fermer
            # proprement les chaînes/objets/tableaux ouverts pour récupérer un
            # résultat PARTIEL exploitable (ex: les positions déjà générées).
            repaired = BaseAgent._repair_truncated_json(text)
            if repaired is not None:
                try:
                    return json.loads(repaired)
                except json.JSONDecodeError:
                    pass
            # Inclut un aperçu de la réponse dans le message d'erreur pour le debug
            preview = original[:200].replace('\n', ' ')
            raise ValueError(f"JSON invalide: {e} | Reponse: {preview!r}") from e

    # ┌─────────────────────────────────────────────────────────────────────────┐
    # │  _repair_truncated_json() - RÉPARATION D'UN JSON COUPÉ EN PLEIN MILIEU  │
    # │  Ferme les chaînes, objets et tableaux restés ouverts par la troncature.│
    # │  Retourne une string JSON candidate, ou None si irréparable.            │
    # └─────────────────────────────────────────────────────────────────────────┘

    @staticmethod
    def _repair_truncated_json(text: str):
        if not text:
            return None
        # Parcours caractère par caractère en suivant l'état (dans une chaîne ?
        # quels conteneurs ouverts ?). On ignore les caractères échappés.
        stack        = []     # pile des conteneurs ouverts : '{' ou '['
        in_string    = False
        escaped      = False
        for ch in text:
            if in_string:
                if escaped:
                    escaped = False
                elif ch == '\\':
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch in '{[':
                stack.append(ch)
            elif ch == '}' and stack and stack[-1] == '{':
                stack.pop()
            elif ch == ']' and stack and stack[-1] == '[':
                stack.pop()

        repaired = text
        # 1) Si on est resté dans une chaîne ouverte, on la ferme.
        if in_string:
            repaired += '"'
        # 2) Supprime une éventuelle virgule traînante (ex: '..."poids": 0.07,')
        #    qui invaliderait le JSON une fois les conteneurs fermés.
        stripped = repaired.rstrip()
        if stripped.endswith(','):
            repaired = stripped[:-1]
        # 3) Ferme les conteneurs ouverts dans l'ordre inverse.
        for opener in reversed(stack):
            repaired += '}' if opener == '{' else ']'
        return repaired if stack or in_string else None


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║  DÉFINITIONS DES OUTILS (Tool Schemas pour l'API Anthropic)                ║
# ║  Ces dicts sont passés dans kwargs["tools"] lors de l'appel API.           ║
# ║  Ils décrivent AU LLM quels outils existent et comment les appeler.        ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  MARKET_DATA_TOOLS - Outils de données de marché                           │
# │  Utilisés par : EquityResearchAgent (via tool use)                         │
# │  Implémentés dans : tools/market_data.py                                   │
# └─────────────────────────────────────────────────────────────────────────────┘

MARKET_DATA_TOOLS = [
    {
        "name": "get_stock_info",
        # Ce que le LLM voit : description courte pour décider quand appeler cet outil
        "description": "Prix courant, capitalisation, secteur et volume d'un titre",
        "input_schema": {
            # Schéma JSON Schema : définit les paramètres que le LLM doit fournir
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string"
                    # Le LLM doit fournir un ticker valide (ex: "NVDA", "ASML.AS")
                }
            },
            "required": ["ticker"],  # "ticker" est obligatoire
        },
    },
    {
        "name": "get_financials",
        "description": "Ratios financiers: P/E, EV/EBITDA, marges, ROE, croissance",
        "input_schema": {
            "type": "object",
            "properties": {"ticker": {"type": "string"}},
            "required": ["ticker"],
        },
    },
    {
        "name": "get_price_history",
        "description": "Performance et volatilite annualisee sur une periode",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "period": {
                    "type": "string",
                    "default": "1y"
                    # Valeurs acceptées par yfinance : "1d","5d","1mo","3mo","6mo","1y","2y","5y"
                },
            },
            "required": ["ticker"],
            # "period" est optionnel → le LLM peut l'omettre (défaut "1y")
        },
    },
]

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  PORTFOLIO_TOOLS - Outil de métriques portefeuille                         │
# │  Utilisé par : RiskManagementAgent uniquement                              │
# │  Implémenté dans : tools/financial_metrics.py                              │
# └─────────────────────────────────────────────────────────────────────────────┘

PORTFOLIO_TOOLS = [
    {
        "name": "compute_portfolio_metrics",
        "description": "Calcule volatilite, beta, tracking error et correlations",
        "input_schema": {
            "type": "object",
            "properties": {
                "positions": {
                    "type": "array",          # Liste de positions
                    "items": {
                        "type": "object",
                        "properties": {
                            "ticker": {"type": "string"},  # ex: "NVDA"
                            "poids":  {"type": "number"},  # ex: 0.065 (6.5%)
                        },
                    },
                    # Le LLM doit fournir TOUTES les positions du portefeuille
                    # pour que le calcul de volatilité soit correct.
                },
                "period": {"type": "string", "default": "1y"},
                # Période d'historique pour les calculs (1y = 252 jours de bourse)
            },
            "required": ["positions"],
        },
    },
]
