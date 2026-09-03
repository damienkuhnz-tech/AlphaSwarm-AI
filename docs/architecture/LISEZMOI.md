# Schémas d'architecture - AlphaSwarm

Sept diagrammes Mermaid, leurs rendus PNG (2 352 px de large, fond blanc, pour
Word) et SVG (vectoriel, fond transparent - à privilégier pour l'impression).

## Vue d'ensemble

| Fichier | Contenu | Format |
|---|---|---|
| `architecture_AlphaSwarm` | Architecture générale : les cinq agents, la boucle de correction, le blocage sur verdict d'échec | portrait |
| `garde_fou_risque` | Le mécanisme « calcul d'abord, jugement ensuite » | paysage |

## Un diagramme par agent - dossier `agents/`

| Fichier | Ce qu'il montre |
|---|---|
| `agent_1_mandat` | La réconciliation profil ↔ bêta, la table des cinq enveloppes de risque, le classement sectoriel - tout est décidé avant l'appel |
| `agent_2_recherche` | Les quatre chemins de construction de l'univers, puis la collecte parallèle et l'analyse par titre |
| `agent_3_portefeuille` | Le poids maximum effectif recalculé en amont, la renormalisation des poids en aval |
| `agent_4_risque` | Le moteur quantitatif, la branche dégradée quand il échoue, et les trois garde-fous |
| `agent_5_execution` | Les règles d'exécution imposées, et le fait qu'aucun fichier n'existe avant l'approbation |

Les cinq suivent la même structure en trois bandes : **ce que Python prépare**,
**ce que le modèle décide**, **ce que Python corrige ensuite**. Cette répétition
est voulue : elle rend visible le patron d'architecture commun à tous les agents.

## Code couleur

Il porte une information, il ne décore pas. À reprendre en légende de figure
dans le mémoire :

| Couleur | Signification |
|---|---|
| Vert | calcul déterministe en Python - seedé, reproductible |
| Ocre | étape confiée au jugement du modèle de langage |
| Bleu | entrée, sortie, interaction humaine |
| Rouge | blocage, ou fonctionnement dégradé |
| Blanc | source de données externe, ou point de décision |

Sur les cinq agents, un seul est majoritairement vert - et c'est celui qui a le
dernier mot. C'est la thèse du travail, lisible d'un coup d'œil.

## Regénérer les images après modification

```bash
npm install -g @mermaid-js/mermaid-cli
mmdc -i architecture_AlphaSwarm.mmd -o architecture_AlphaSwarm.png -b white -s 3
mmdc -i architecture_AlphaSwarm.mmd -o architecture_AlphaSwarm.svg -b transparent
```

Le bloc de configuration en tête de chaque `.mmd` fixe la police, l'espacement,
la courbure des arêtes et surtout `wrappingWidth` - c'est ce paramètre qui évite
les coupures de texte disgracieuses au milieu des libellés.

## Ce qui a changé par rapport à la version d'origine

- Le moteur quantitatif `quant/` apparaît enfin. L'ancien schéma montrait
  `financial_metrics.py` et `backtest.py` - ce dernier n'existe plus, et la
  contribution centrale du travail était absente du diagramme.
- Les six « LAYER » numérotés ont disparu : c'est du vocabulaire d'architecture
  qui n'apprend rien au lecteur.
- Les cinq flèches identiques vers une boîte « moteur LLM » ont été retirées.
  Elles disaient seulement « tous les agents utilisent un modèle ». Le fait
  remarquable - le modèle n'a pas la main sur les chiffres du risque - est
  désormais porté par la couleur et par les schémas dédiés.
- Les cinq doubles flèches vers l'état partagé sont devenues des flèches simples
  entre agents, étiquetées avec les clés de l'état (`mandate`, `research`,
  `portfolio`, `risk_report`). Même information, lecture immédiate.
- Chaque flèche porte un libellé. Une flèche sans libellé signifie « lié d'une
  manière ou d'une autre », ce qui n'est pas une information.
