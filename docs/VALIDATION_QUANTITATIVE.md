# FinAgent — Moteur de validation quantitative & refonte du Risk Agent

> Document de référence pour le mémoire de Bachelor. Décrit l'architecture du
> nouveau module `quant/`, la refonte du `RiskManagementAgent`, le dashboard
> de validation, les optimisations de performance, et — pour chaque choix —
> sa **justification académique** (quel biais il réduit, quelle critique du
> jury il adresse).

---

## 1. Problème adressé

La version précédente du Risk Agent souffrait des faiblesses classiques
reprochées aux travaux appliqués en finance quantitative :

| Critique type d'un jury | Situation avant | Situation après |
|---|---|---|
| Validation expérimentale insuffisante | Backtest unique 1 an, poids figés | Backtest 10 ans rebalancé + 4 protocoles de validation |
| Absence de validation out-of-sample | Aucune | Split chronologique 80/20 + walk-forward |
| Faible significativité statistique | Un point de mesure unique | Bootstrap 1 000 simulations, IC à 95 % |
| Absence de benchmark | Un seul indice | Mandat + S&P 500 + Nasdaq + équipondéré + 200 portefeuilles aléatoires |
| Manque de robustesse | — | 5 stress tests historiques + Monte Carlo 2 000 trajectoires |
| Manque de reproductibilité | Données retéléchargées à chaque run | Toutes les simulations seedées, prix cachés sur disque |
| Conclusions trop affirmatives | Verdict 100 % LLM | Compliance PASS/FAIL calculée en Python + garde-fou déterministe sur le LLM |

**Principe architectural : « calcul d'abord, jugement ensuite ».**
Tout ce qui est chiffrable est calculé en Python (déterministe, auditable,
reproductible). Le LLM n'intervient que pour l'interprétation et les
recommandations — et son verdict ne peut pas contredire les tests calculés.

---

## 2. Architecture du module `quant/`

```
quant/
├── data.py         Chargement des prix — cache mémoire + disque PAR TICKER,
│                   téléchargement batch des seuls manquants (1 appel réseau)
├── metrics.py      Bibliothèque de métriques (fonctions pures, testables)
├── engine.py       Séries de rendements du portefeuille (rebalancement mensuel)
├── validation.py   Train/test split, walk-forward, bootstrap, Monte Carlo
├── stress.py       Stress tests sur crises historiques réelles
├── benchmarks.py   Multi-benchmarks + test placebo (portefeuilles aléatoires)
├── compliance.py   Contraintes du mandat → tests PASS/FAIL mécaniques
└── report.py       Orchestration → dict JSON unique pour l'agent et l'UI
```

Point d'entrée unique :

```python
from quant import run_full_validation
rapport = run_full_validation(positions, mandate, portfolio,
                              benchmark_etf="URTH", benchmark_name="MSCI World")
```

Le rapport (~40 Ko de JSON) alimente à la fois le `RiskReport` Pydantic
(champ `validation_quantitative`) et le dashboard frontend.

### 2.1 Simulation du portefeuille (`engine.py`)

- **Rebalancement mensuel vers les poids cibles** (mode par défaut) : entre
  deux rebalancements, les poids dérivent avec les prix, puis sont réalignés.
  C'est la simulation correcte d'une politique d'allocation — l'ancien code
  supposait des poids constants chaque jour, ce qui équivaut à un
  rebalancement quotidien gratuit, irréaliste.
- Le **turnover induit** par le rebalancement est mesuré et rapporté.
- Titres sans historique : exclus, poids renormalisés, **exclusions
  rapportées** (transparence méthodologique).

### 2.2 Métriques (`metrics.py`)

Performance : rendement total, CAGR, alpha de Jensen, beta, Sharpe, Sortino,
Calmar, Treynor, Information Ratio, hit ratio mensuel.
Risque : volatilité, volatilité à la baisse, max drawdown (+ durée et temps de
récupération), VaR/CVaR historiques 95/99 %, tracking error, corrélation.
Structure : HHI, nombre effectif de positions (1/HHI), ratio de
diversification (Choueifaty & Coignard 2008), expositions sectorielles et
géographiques.
Rolling : Sharpe, beta, volatilité sur fenêtre glissante 126 jours.

Choix documentés :
- **Taux sans risque 2 %** (l'hypothèse 0 % de l'ancien code surestimait le Sharpe).
- **VaR/CVaR empiriques** (quantiles) plutôt que gaussiennes : capture
  l'asymétrie et les queues épaisses des rendements réels.
- 252 jours de bourse par an (convention standard).

---

## 3. Les quatre protocoles de validation et leur justification

### 3.1 Train / Test split (80/20 chronologique)

Coupe l'historique en 80 % « in-sample » / 20 % « out-of-sample » (les plus
récents). Les métriques sont rapportées côte à côte, avec le Δ Sharpe.

**Justification.** Répond directement à la critique « absence de validation
out-of-sample ». Le split est **chronologique et non aléatoire** : les données
financières sont séquentielles, un mélange aléatoire ferait fuiter de
l'information du futur vers le passé (look-ahead bias). Une dégradation
modérée IS → OOS est attendue ; un effondrement signale du sur-ajustement.

**Limite assumée (documentée dans l'UI et le prompt).** Les titres ont été
sélectionnés en connaissant (indirectement) leur historique : le biais de
sélection rétrospectif ne peut pas être totalement éliminé sur un backtest
d'allocation. Il est encadré par les trois protocoles suivants.

### 3.2 Walk-forward (train 5 ans / test 1 an, fenêtres glissantes)

Sur 10 ans d'historique → ~4-5 fenêtres de test disjointes. Rapporte
CAGR/Sharpe/vol/drawdown **moyens ± écart-type** et la **stabilité** (part de
fenêtres profitables).

**Justification.** Une bonne performance sur une seule période peut être de la
chance (un seul tirage). La dispersion inter-fenêtres quantifie la robustesse
temporelle — c'est la réponse standard de la littérature praticienne
(Pardo, *The Evaluation and Optimization of Trading Strategies*) au problème
du backtest unique.

### 3.3 Bootstrap par blocs (1 000 simulations, seed 42)

Ré-échantillonnage par **blocs de 21 jours** des rendements **conjoints**
(portefeuille + benchmark sur les mêmes blocs). Produit les distributions
empiriques du CAGR, du Sharpe, du max drawdown, avec **IC à 95 %**, et la
**probabilité de battre le benchmark**.

**Justification.** Répond à « faible significativité statistique » : au lieu
d'un Sharpe ponctuel (1.19), on rapporte « Sharpe médian 1.18, IC95
[0.47 ; 2.11] » — si l'IC exclut 0, la performance est significative. Les
blocs préservent l'autocorrélation des rendements (le bootstrap i.i.d. la
détruirait) ; le ré-échantillonnage conjoint préserve la corrélation
portefeuille/benchmark (sinon la probabilité de surperformance serait biaisée).

### 3.4 Monte Carlo non-paramétrique (2 000 trajectoires à 1 an, seed 43)

Trajectoires futures simulées par bootstrap de blocs des rendements
historiques. Produit : probabilité de perte, P(perte > 10 %), VaR/CVaR 95 et
99 % à 1 an, probabilité d'atteindre le rendement cible, fan chart p5-p95.

**Justification.** Contrairement au Monte Carlo gaussien classique, aucune
hypothèse de normalité — les queues épaisses observées sont conservées dans
les scénarios. Donne au PM une lecture *prospective* du risque (l'historique
seul est rétrospectif).

### 3.5 Stress tests historiques

Cinq fenêtres de crise réelles : krach COVID (02-04/2020), choc
inflation/taux (01-10/2022), bear market 2022, crise bancaire (03-05/2023),
bull market 2023-2024. Pour chacune : rendement vs benchmark, max drawdown,
temps de récupération, **couverture** (part du portefeuille disposant de
données sur la fenêtre).

**Justification.** Pratique institutionnelle standard : les crises réelles
capturent la montée des corrélations en période de stress, que les modèles
paramétriques sous-estiment systématiquement.

### 3.6 Benchmarks et test placebo

- Benchmark du mandat + S&P 500 + Nasdaq (TE, IR, hit ratio pour chacun).
- **Équipondéré sur les mêmes titres** : isole la valeur de la *pondération*.
- **200 portefeuilles aléatoires** (poids Dirichlet, seed 123) sur le même
  univers : le percentile du Sharpe du portefeuille dans cette distribution
  est un **test placebo** — si le portefeuille est au 50ᵉ percentile de
  portefeuilles aléatoires, l'allocation n'apporte rien.

**Justification.** Répond à « absence de benchmark » et « conclusions trop
affirmatives » : la surperformance est confrontée à des contrefactuels, dont
le hasard pur.

---

## 4. Mandate Compliance — PASS/FAIL mécanique

`quant/compliance.py` transforme chaque contrainte du mandat en test unitaire
objectif : volatilité max, tracking error max, plage de beta, drawdown max,
concentration top 10, poids max par position, nombre de positions, bornes de
cash, contraintes sectorielles et géographiques (matching insensible aux
accents), exclusions (vérification lexicale), critères ESG (marqué N/A —
**limite documentée** : non vérifiable sans fournisseur de données ESG).

Sortie : `{nom, catégorie, limite, valeur mesurée, PASS/FAIL/N-A}` + verdict
global. **Le LLM n'intervient pas dans cette section** — le jury voit des
tests calculés, pas des affirmations.

---

## 5. Refonte du RiskManagementAgent

Nouveau flux (`agents/risk_management_agent.py`) :

1. `run_full_validation()` — tout le calcul, en Python.
2. **Un seul appel LLM** (au lieu de deux) sur un résumé compact (~800
   tokens) : compliance, IS/OOS, walk-forward, bootstrap, Monte Carlo,
   stress, placebo. Le LLM produit : statut, violations, recommandations,
   commentaire, commentaire méthodologique.
3. **Forçage des métriques** : les chiffres du rapport final sont ceux du
   moteur, jamais ceux du LLM.
4. **Garde-fou déterministe** :
   - des tests FAIL + verdict LLM « PASS » → rétrogradé « AJUSTER » ;
   - aucun test FAIL + verdict LLM « FAIL » → ramené à « PASS » ;
   - chaque test FAIL non mentionné par le LLM devient une violation
     mécanique (aucun échec ne peut être omis) ;
   - sévérités hors vocabulaire normalisées (évite les `ValidationError`).

**Justification académique.** La division du travail LLM/calcul est le cœur
de la contribution du mémoire : elle rend le système *auditable* (chaque
chiffre est retraçable à un calcul) tout en conservant la valeur ajoutée du
LLM (interprétation, recommandations contextualisées). Le garde-fou borne
formellement le risque d'hallucination sur la décision de conformité.

---

## 6. Dashboard de validation (UI)

`renderRisk()` (static/js/render-risk.js) rend désormais 11 sections avec
navigation par ancres : Executive Summary (verdict, jauge, 8 KPI),
Violations & Recommandations, Mandate Compliance (tableau PASS/FAIL),
Performance (courbe 10 ans base 100 + tableau complet + structure), Train/Test,
Walk-Forward, Rolling (Sharpe/beta/vol 126 j), Drawdown, Bootstrap
(3 histogrammes + IC), Monte Carlo (fan chart + distribution), Stress Tests
(barres portefeuille vs benchmark), Benchmarks + placebo.

Nouvelles primitives SVG ajoutées à `CHART` (sans dépendance externe, cohérentes
avec la charte existante) : `histogram`, `dlines` (multi-lignes datées),
`fanChart`, `hbars`. **Repli automatique** sur l'ancien rendu si le moteur
quant est indisponible (réseau coupé), avec bandeau explicatif.

Correctif au passage : la fonction `_escapeHtml` était appelée (y compris par
du code préexistant) **sans jamais être définie** — elle est maintenant
implémentée (échappement XSS de tout contenu LLM/marché avant `innerHTML`).

---

## 7. Optimisations de performance

| Optimisation | Fichier | Avant | Après | Justification |
|---|---|---|---|---|
| Cache de prix **par ticker** (mémoire + disque, clé datée) + download batch des seuls manquants | `quant/data.py` | Chaque itération Risk retéléchargeait tous les prix (2 downloads × N itérations) | 1 download le 1ᵉʳ run du jour ; itérations suivantes ~0,7 s | I/O réseau = goulot dominant ; le cache disque rend aussi les runs **rejouables** (reproductibilité) |
| Validation quantitative vectorisée numpy (bootstrap 1 000 + MC 2 000 en matrices) | `quant/validation.py` | — | ~1,5 s de calcul pur | Boucles Python remplacées par `np.cumprod`/`np.maximum.accumulate` sur matrices (n_sims × jours) |
| **1 appel LLM au lieu de 2** dans le Risk Agent (jugement + commentaire backtest fusionnés) | `agents/risk_management_agent.py` | 2 appels séquentiels | 1 appel | Latence LLM ≈ 15-30 s/appel : gain direct de ~50 % sur l'étape Risk |
| Prompt de jugement compact (~800 tokens) au lieu du JSON complet des positions | idem | ~2 500 tokens | ~800 tokens | Moins de tokens = latence et coût réduits, sans perte d'information décisionnelle |
| `/api/quotes` parallélisé (ThreadPoolExecutor 8 workers) | `api.py` | 5 tickers ≈ 10 s (séquentiel) | 5 tickers ≈ 0,9 s (mesuré) | I/O bound → threads ; l'ordre des résultats est préservé |
| `/api/quotes/live` parallélisé | `api.py` | N × latence fast_info | latence du plus lent (8 tickers ≈ 2,8 s mesuré) | Endpoint pollé toutes les 8 s par l'UI |
| Cache market_data borné (512 entrées) + thread-safe | `tools/market_data.py` | Croissance illimitée, accès concurrent non protégé | Éviction des 25 % plus anciens, verrou | Les endpoints sont désormais multi-threads |

Note : l'agent Research était déjà parallélisé (5 workers) — vérifié, aucun
changement nécessaire.

**Temps de la validation quantitative complète** (22 titres, 10 ans,
1 000 bootstraps, 2 000 Monte Carlo, 5 stress tests, 200 placebos) :
**~2,6 s** au premier run du jour, **~0,7 s** ensuite (mesuré).

---

## 8. Reproductibilité

- Seeds fixes : bootstrap 42, Monte Carlo 43, placebo 123 → résultats
  identiques d'un run à l'autre (vérifié).
- Prix cachés sur disque avec clé datée → un run peut être rejoué à
  l'identique le même jour ; les fichiers de cache peuvent être archivés avec
  le mémoire pour figer les données.
- Le rapport JSON complet est embarqué dans le `RiskReport` exporté
  (`run_<id>.json`) → toute figure du mémoire est régénérable.

## 9. Limites connues (à assumer dans le mémoire)

1. **Biais de sélection rétrospectif** : les titres sont choisis aujourd'hui
   puis backtestés sur le passé. Encadré (OOS, walk-forward, placebo) mais
   non éliminable sans données point-in-time.
2. **Biais du survivant** : l'univers yfinance ne contient pas les titres
   radiés de la cote.
3. **Coûts de transaction non modélisés** dans le backtest (le turnover est
   mesuré, l'impact des frais peut être borné : turnover × coût unitaire).
4. **ESG non vérifiable** sans fournisseur de données dédié (test marqué N/A).
5. Les contraintes géographiques reposent sur le champ `geographie` déclaré
   par l'agent de construction (matching lexical).
