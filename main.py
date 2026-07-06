"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  ALPHASWARM — POINT D'ENTRÉE (ÉTAPE 0 / PREMIER FICHIER EXÉCUTÉ)              ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Rôle : parser les arguments CLI et lancer le workflow.                      ║
║  Ce fichier ne contient aucune logique métier — il délègue tout au runner.  ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Flux de démarrage :                                                         ║
║    python main.py                                                            ║
║        ↓  main() parse les args                                              ║
║        ↓  run_workflow() → orchestrator/runner.py                            ║
║        ↓  build_workflow() → orchestrator/workflow.py                        ║
║        ↓  WorkflowEngine.run() → 8 agents s'enchaînent                      ║
╚══════════════════════════════════════════════════════════════════════════════╝

Usage :
    python main.py
    python main.py --capital 50000000 --benchmark "S&P 500"
"""

# ── Compatibilité Windows UTF-8 ───────────────────────────────────────────────
# Rich utilise des caractères Unicode (boîtes, flèches, couleurs ANSI).
# Sur Windows, la console par défaut est cp1252 → UnicodeEncodeError.
# On force utf-8 sur stdout/stderr AVANT tout autre import.
import sys
import io

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


# ── Imports ───────────────────────────────────────────────────────────────────
# argparse : module Python natif pour lire les arguments passés en ligne de commande.
import argparse

# run_workflow : unique point de contact avec l'orchestrateur.
# Tout le workflow (agents, affichage, validation humaine) s'y déroule.
from orchestrator.runner import run_workflow


# ── Point d'entrée ────────────────────────────────────────────────────────────
# Conception : main() ne fait que deux choses — parser et déléguer.
# Aucun agent, aucun LLM, aucun affichage n'est instancié ici.

def main():

    # ── Arguments CLI ─────────────────────────────────────────────────────────
    # Tous ont des valeurs par défaut : le workflow tourne sans aucun argument.
    # Ces 4 valeurs forment le PortfolioState initial (voir models/state.py).
    parser = argparse.ArgumentParser(
        description="AlphaSwarm - Multi-Agent Portfolio Management"
    )

    # Stratégie libre (texte) → transmise telle quelle au MandateAgent
    parser.add_argument("--strategie", default="long-only equity global diversifie")

    # Capital en USD → utilisé pour calculer valeur_usd de chaque position
    parser.add_argument("--capital", type=float, default=100_000_000)

    # Benchmark → utilisé pour calculs tracking error et scoring
    parser.add_argument("--benchmark", default="MSCI World")

    # Horizon → guide le niveau de risque accepté par les agents
    parser.add_argument("--horizon", default="3-5 ans")

    # Profil de risque → pilote la segmentation sectorielle bêta et le budget risque
    parser.add_argument(
        "--profil_risque",
        default="equilibre",
        choices=["conservateur", "modere", "equilibre", "dynamique", "agressif"],
    )

    # Perte max tolérée sur 12 mois (%) → renforce drawdown_max si plus conservateur
    parser.add_argument("--perte_max_toleree", type=float, default=None)

    # Priorité principale → oriente le type_signal des idées
    parser.add_argument(
        "--priorite_principale",
        default="croissance",
        choices=["preservation", "revenus", "croissance", "performance"],
    )

    args = parser.parse_args()

    # ── Lancement ─────────────────────────────────────────────────────────────
    run_workflow(
        strategie=args.strategie,
        capital=args.capital,
        benchmark=args.benchmark,
        horizon=args.horizon,
        profil_risque=args.profil_risque,
        perte_max_toleree=args.perte_max_toleree,
        priorite_principale=args.priorite_principale,
    )


# ── Guard d'exécution ─────────────────────────────────────────────────────────
# Garantit que main() n'est appelé que si on lance "python main.py"
# et non si ce module est importé par un autre fichier.
if __name__ == "__main__":
    main()
