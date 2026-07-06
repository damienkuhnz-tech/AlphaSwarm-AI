# AlphaSwarm — Plateforme multi-agent de gestion de portefeuille

Travail de bachelor. AlphaSwarm orchestre cinq agents spécialisés qui couvrent
le cycle complet de la gestion de portefeuille institutionnelle, de la
définition du mandat jusqu'à la préparation des ordres d'exécution.

## Architecture

Pipeline strictement séquentiel — chaque agent consomme la sortie du précédent :

| # | Agent | Rôle |
|---|-------|------|
| 1 | **Mandate Agent** | Analyse de cohérence du mandat (stratégie, benchmark, contraintes de risque, profil client) |
| 2 | **Equity Research Agent** | Génération d'idées, collecte de données de marché, rapports de recherche par titre et par secteur |
| 3 | **Portfolio Construction Agent** | Construction et pondération du portefeuille sous contraintes |
| 4 | **Risk Management Agent** | Validation quantitative (backtest 10 ans, walk-forward, bootstrap, Monte Carlo, stress tests) + jugement LLM sous garde-fou déterministe |
| 5 | **Execution Agent** | Préparation des ordres et validation PM |

Modules principaux :

- `agents/` — les cinq agents (LLM : API Anthropic, fallback Groq)
- `quant/` — moteur de validation quantitative 100 % Python (voir `docs/VALIDATION_QUANTITATIVE.md`)
- `orchestrator/` — enchaînement du pipeline et gestion d'état
- `models/` — schémas Pydantic partagés
- `api.py` — serveur Flask (port 5001) : API de pilotage + interface web
- `finagent_full_interface.html` — interface de la plateforme (`/app`)
- `landing/` — page d'accueil (`/`)
- `docs/architecture/` — diagrammes Mermaid

## Installation

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
copy .env.example .env          # puis renseigner les clés
```

Variables d'environnement requises dans `.env` :

- `ANTHROPIC_API_KEY` — clé API Anthropic (obligatoire)
- `FINNHUB_API_KEY`, `ALPHA_VANTAGE_API_KEY` — données de marché enrichies (optionnel)

## Lancement

```bash
start.bat            # Windows : démarre le serveur et ouvre le navigateur
# ou
python api.py        # puis ouvrir http://localhost:5001
```

- `/` — présentation du projet
- `/app` — plateforme (définir le mandat, puis lancer les agents dans l'ordre du pipeline)

## Validation quantitative

Le Risk Agent s'appuie sur un moteur déterministe (`quant/`) : backtest
rebalancé mensuellement, découpage train/test, walk-forward, bootstrap par
blocs, simulation Monte Carlo, stress tests historiques et vérification de
conformité au mandat. Le verdict LLM ne peut pas contredire les tests :
un échec quantitatif force le rejet. Détails et justifications
méthodologiques dans `docs/VALIDATION_QUANTITATIVE.md`.
