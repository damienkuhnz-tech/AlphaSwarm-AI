"""
Runner CLI - interface Rich pour le Portfolio Manager.
Gère l'affichage en temps réel, les points de validation humaine
et l'export des ordres.
"""
import json
import uuid
import os
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt, Confirm
from rich import box
from rich.text import Text

from models.state import PortfolioState
from config.settings import settings

console = Console(force_terminal=True, legacy_windows=False)


# ── Helpers d'affichage ───────────────────────────────────────────────

def _header() -> None:
    console.print(Panel(
        "[bold white]AlphaSwarm[/bold white]  [dim]Multi-Agent Portfolio Management[/dim]\n"
        "[dim]Global Long-Only Equity  |  Claude Sonnet 4.6[/dim]",
        border_style="gold1",
        padding=(0, 2),
    ))


def _step_badge(step: str, status: str, duration: float = 0.0) -> None:
    icons = {
        "running": "[yellow]⟳[/yellow]",
        "done":    "[green]✓[/green]",
        "warn":    "[yellow]![/yellow]",
        "fail":    "[red]✗[/red]",
    }
    icon = icons.get(status, " ")
    dur = f"[dim]{duration:.1f}s[/dim]" if duration else ""
    console.print(f"  {icon}  {step:<35} {dur}")


def _show_portfolio(portfolio) -> None:
    if not portfolio:
        return
    table = Table(
        title="Portefeuille Construit",
        box=box.SIMPLE_HEAD,
        header_style="bold cyan",
        show_footer=True,
    )
    table.add_column("Ticker",   style="bold white",  footer="TOTAL")
    table.add_column("Nom",      style="dim")
    table.add_column("Secteur",  style="cyan")
    table.add_column("Poids",    justify="right",
                     style="green", footer=f"{(1-portfolio.cash_poids):.1%}")
    table.add_column("Valeur USD", justify="right")
    table.add_column("Rôle",     style="dim", max_width=30)

    for p in sorted(portfolio.positions, key=lambda x: x.poids, reverse=True):
        table.add_row(
            p.ticker,
            p.nom[:28],
            p.secteur[:18],
            f"{p.poids:.1%}",
            f"${p.valeur_usd:>12,.0f}",
            p.role_portefeuille[:30],
        )
    # Cash row
    table.add_row(
        "CASH", "", "",
        f"{portfolio.cash_poids:.1%}",
        f"${portfolio.cash_valeur_usd:>12,.0f}",
        "Liquidités",
        style="dim",
    )
    console.print(table)


def _show_risk(risk) -> None:
    if not risk:
        return
    color = {"PASS": "green", "AJUSTER": "yellow", "FAIL": "red"}.get(
        risk.statut, "white"
    )
    console.print(
        f"\n  Risk Status : [{color}]{risk.statut}[/{color}]"
    )
    if risk.violations:
        for v in risk.violations:
            sev_color = {"MINEURE": "yellow", "MAJEURE": "orange3", "CRITIQUE": "red"}.get(
                v.severite, "white"
            )
            console.print(
                f"  [{sev_color}]⚠[/{sev_color}]  [{sev_color}]{v.severite}[/{sev_color}] - {v.detail}"
            )
    if risk.recommandations:
        for r in risk.recommandations:
            console.print(f"  [dim]→ {r}[/dim]")


def _show_orders(execution) -> None:
    if not execution:
        return
    table = Table(
        title=f"Ordres préparés - Export OMS ({execution.nombre_ordres} ordres)",
        box=box.SIMPLE_HEAD,
        header_style="bold magenta",
    )
    table.add_column("Ticker",    style="bold white")
    table.add_column("Action",    style="bold")
    table.add_column("Valeur USD",  justify="right")
    table.add_column("Poids cible", justify="right")
    table.add_column("Priorité")
    table.add_column("Algo")

    for o in sorted(execution.ordres, key=lambda x: (x.priorite != "HIGH", x.valeur_usd), reverse=False):
        action_color = "green" if o.action == "BUY" else "red"
        prio_color = {"HIGH": "red", "NORMAL": "yellow", "LOW": "dim"}.get(o.priorite, "white")
        table.add_row(
            o.ticker,
            f"[{action_color}]{o.action}[/{action_color}]",
            f"${o.valeur_usd:>12,.0f}",
            f"{o.poids_cible:.1%}",
            f"[{prio_color}]{o.priorite}[/{prio_color}]",
            o.algo_suggere,
        )
    console.print(table)
    console.print(
        f"\n  [dim]Coûts estimés : ${execution.couts_transaction.total_estime_usd:,.0f} "
        f"({execution.couts_transaction.total_bps:.0f}bps)[/dim]"
    )


def _export_orders(state: PortfolioState, run_id: str) -> str:
    """Exporte les ordres en JSON dans le dossier exports/."""
    Path(settings.EXPORTS_DIR).mkdir(exist_ok=True)
    execution = state.get("execution_output")
    if not execution:
        return ""

    payload = {
        "run_id": run_id,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "portfolio_manager": "PM_VALIDATED",
        "statut": "APPROUVE_POUR_OMS",
        "capital_investi_usd": execution.capital_investi,
        "capital_cash_usd": execution.capital_cash,
        "ordres": [o.model_dump() for o in execution.ordres],
        "couts_transaction": execution.couts_transaction.model_dump(),
    }

    filepath = os.path.join(settings.EXPORTS_DIR, f"orders_{run_id}.json")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return filepath


def _export_full_run(state: PortfolioState, run_id: str) -> str:
    """Exporte le run complet en JSON dans outputs/."""
    Path(settings.OUTPUTS_DIR).mkdir(exist_ok=True)

    def _serial(obj):
        if hasattr(obj, "model_dump"):
            return obj.model_dump()
        if isinstance(obj, list):
            return [_serial(i) for i in obj]
        return obj

    payload = {
        "run_id": run_id,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "mandate":    _serial(state.get("mandate")),
        "ideas":      _serial(state.get("ideas", [])),
        "research":   _serial(state.get("research", [])),
        "portfolio":  _serial(state.get("portfolio")),
        "risk":       _serial(state.get("risk_report")),
        "execution":  _serial(state.get("execution_output")),
    }

    filepath = os.path.join(settings.OUTPUTS_DIR, f"run_{run_id}.json")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return filepath


# ── Runner principal ──────────────────────────────────────────────────

def run_workflow(
    strategie: str = "long-only equity global diversifié",
    capital: float = 100_000_000,
    benchmark: str = "MSCI World",
    horizon: str = "3-5 ans",
    profil_risque: str = "equilibre",
    perte_max_toleree: float = None,
    priorite_principale: str = "croissance",
) -> PortfolioState:
    """Point d'entrée principal du workflow."""
    import time
    from orchestrator.workflow import build_workflow

    settings.validate()

    # Chargement des agents AVANT l'affichage (masque la latence d'init)
    with console.status("[bold gold1]Chargement des 5 agents...[/bold gold1]", spinner="dots"):
        workflow = build_workflow()

    run_id = uuid.uuid4().hex[:8].upper()

    _header()
    console.print(f"\n  [dim]Run ID : {run_id}  |  {datetime.now().strftime('%Y-%m-%d %H:%M')}[/dim]\n")

    # État initial
    initial_state: PortfolioState = {
        "strategie":            strategie,
        "capital":              capital,
        "benchmark":            benchmark,
        "horizon":              horizon,
        "profil_risque":        profil_risque,
        "perte_max_toleree":    perte_max_toleree,
        "priorite_principale":  priorite_principale,
        "mandate":              None,
        "ideas":               None,
        "research":            None,
        "portfolio":           None,
        "risk_report":         None,
        "execution_output":    None,
        "current_step":        "mandate",
        "portfolio_iteration": 1,
        "errors":              [],
        "requires_human_review": False,
        "human_approved":      False,
        "run_id":              run_id,
    }

    console.print("  [bold]Lancement du workflow...[/bold]\n")

    step_labels = {
        "mandate":    "1/5  Mandate Agent",
        "research":   "2/5  Equity Research Agent",
        "portfolio":  "3/5  Portfolio Construction Agent",
        "risk":       "4/5  Risk Management Agent",
        "execution":  "5/5  Execution Agent",
    }
    step_times: dict = {}

    def on_step_done(node: str, state: PortfolioState) -> None:
        """Callback appelé après chaque agent."""
        t1 = time.time()
        dt = t1 - step_times.get("_last", t1)
        step_times["_last"] = t1

        label = step_labels.get(node, node)
        risk_r = state.get("risk_report")

        status = "done"
        if node == "risk" and risk_r and risk_r.statut != "PASS":
            status = "warn"

        _step_badge(label, status, dt)

    step_times["_last"] = time.time()
    final_state = workflow.run(initial_state, on_step_done=on_step_done)

    console.print()

    # ── Affichage des résultats ───────────────────────────────────────
    portfolio  = final_state.get("portfolio")
    risk       = final_state.get("risk_report")
    execution  = final_state.get("execution_output")

    _show_portfolio(portfolio)
    _show_risk(risk)

    # ── Erreurs non fatales remontées par les agents ──────────────────
    # Sans ça, un agent en échec produit un résultat partiel qui paraît
    # « valide » mais vide. On rend les échecs visibles au gérant.
    agent_errors = final_state.get("errors") or []
    if agent_errors:
        console.print("\n  [bold red]⚠ AVERTISSEMENTS[/bold red] - "
                      f"{len(agent_errors)} étape(s) en échec :")
        for err in agent_errors:
            console.print(f"    [red]•[/red] {err}")

    # ── Point de validation humaine ───────────────────────────────────
    console.print("\n" + "─" * 60)
    console.print(
        "\n  [bold yellow]VALIDATION REQUISE[/bold yellow]  "
        "- Aucun ordre ne sera exporté sans votre approbation.\n"
    )

    action = Prompt.ask(
        "  Action",
        choices=["approuver", "rejeter", "voir-ordres", "exporter-run"],
        default="voir-ordres",
    )

    if action == "voir-ordres":
        _show_orders(execution)
        action = Prompt.ask(
            "\n  Confirmer",
            choices=["approuver", "rejeter"],
            default="approuver",
        )

    if action == "approuver":
        filepath = _export_orders(final_state, run_id)
        run_path = _export_full_run(final_state, run_id)
        console.print(
            f"\n  [green]✓[/green]  Ordres exportés : [bold]{filepath}[/bold]"
        )
        console.print(
            f"  [green]✓[/green]  Run complet     : [bold]{run_path}[/bold]"
        )
        console.print(
            "\n  [dim]Transmettez le fichier d'ordres à votre OMS externe.[/dim]\n"
        )
    elif action == "exporter-run":
        run_path = _export_full_run(final_state, run_id)
        console.print(f"\n  [green]✓[/green]  Run exporté : [bold]{run_path}[/bold]\n")
    else:
        console.print("\n  [red]✗[/red]  Workflow rejeté - aucun ordre exporté.\n")

    return final_state
