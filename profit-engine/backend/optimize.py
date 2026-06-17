#!/usr/bin/env python3
"""
Profit Engine — Optimiseur automatique
Lance: python optimize.py

Teste 2160 combinaisons de paramètres sur 2 ans de données réelles
(BTC, ETH, SOL, SPY, QQQ) avec commission + slippage réalistes.
Sauvegarde automatiquement la meilleure config dans optimized_config.json.
"""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeElapsedColumn
from rich import box

from config import config
from backtester.optimizer import Optimizer, fetch_data, TOTAL_COMBOS

console = Console()

SYMBOLS = ["BTC-USD", "ETH-USD", "SOL-USD", "SPY", "QQQ"]

# ─── Téléchargement ──────────────────────────────────────────────────────────

def download_all():
    data = {}
    console.print("[bold cyan]📥 Données historiques (2 ans, 1h)...[/]\n")
    for sym in SYMBOLS:
        with console.status(f"  {sym}..."):
            df = fetch_data(sym, period="2y", interval="1h")
        if not df.empty:
            data[sym] = df
            console.print(f"  [green]✓[/] {sym:10s} — {len(df):5,} bougies ({df.index[0].date()} → {df.index[-1].date()})")
        else:
            console.print(f"  [red]✗[/] {sym} — échec du téléchargement")
    return data

# ─── Affichage ───────────────────────────────────────────────────────────────

def print_top_table(top_results, n=20):
    tbl = Table(
        title=f"[bold]Top {n} configurations[/] (scorées sur tous les symboles)",
        box=box.ROUNDED, header_style="bold cyan", show_lines=False
    )
    tbl.add_column("#", width=4, justify="right")
    tbl.add_column("Score", width=8, justify="right")
    tbl.add_column("Return", width=9, justify="right")
    tbl.add_column("Sharpe", width=8, justify="right")
    tbl.add_column("Win%", width=7, justify="right")
    tbl.add_column("PF", width=6, justify="right")
    tbl.add_column("MaxDD", width=7, justify="right")
    tbl.add_column("Trades", width=7, justify="right")
    tbl.add_column("MinSc", width=6)
    tbl.add_column("SL×", width=5)
    tbl.add_column("R:R", width=5)
    tbl.add_column("RSI", width=10)
    tbl.add_column("BB σ", width=6)

    for i, (params, res) in enumerate(top_results[:n], 1):
        sc = res.composite_score
        sc_col = "green" if sc > 1.5 else "yellow" if sc > 0.5 else "red"
        ret_col = "green" if res.total_return_pct > 0 else "red"
        dd_col = "red" if res.max_drawdown_pct > 20 else "yellow" if res.max_drawdown_pct > 10 else "green"
        tbl.add_row(
            str(i),
            f"[{sc_col}]{sc:+.3f}[/]",
            f"[{ret_col}]{res.total_return_pct:+.1f}%[/]",
            f"{res.sharpe_ratio:.2f}",
            f"{res.win_rate:.1f}%",
            f"{res.profit_factor:.2f}",
            f"[{dd_col}]{res.max_drawdown_pct:.1f}%[/]",
            str(res.total_trades),
            str(params.get("min_score_buy", "")),
            str(params.get("stop_loss_atr_mult", "")),
            str(params.get("take_profit_rr", "")),
            f"{params.get('rsi_oversold','')}/{params.get('rsi_overbought','')}",
            str(params.get("bb_std", "")),
        )
    console.print(tbl)


def print_wf_table(wf_windows, wf_consistency, symbol):
    tbl = Table(title=f"Walk-Forward ({symbol}) — validation hors-échantillon", box=box.SIMPLE)
    tbl.add_column("Fenêtre", width=10)
    tbl.add_column("Return", width=10, justify="right")
    tbl.add_column("Sharpe", width=8, justify="right")
    tbl.add_column("Win%", width=7, justify="right")
    tbl.add_column("Trades", width=8, justify="right")
    tbl.add_column("Résultat", width=12)
    for w in wf_windows:
        ret_col = "green" if w.profitable else "red"
        tbl.add_row(
            f"Période {w.period}",
            f"[{ret_col}]{w.total_return_pct:+.2f}%[/]",
            f"{w.sharpe_ratio:.2f}",
            f"{w.win_rate:.1f}%",
            str(w.total_trades),
            f"[{ret_col}]{'✅ Profitable' if w.profitable else '❌ Perte'}[/]",
        )
    tbl.add_section()
    cons_col = "green" if wf_consistency >= 75 else "yellow" if wf_consistency >= 50 else "red"
    tbl.add_row("CONSISTANCE", "", "", "", "", f"[{cons_col}]{wf_consistency:.0f}% fenêtres +[/]")
    console.print(tbl)


def save_config(best_params: dict, result, wf_consistency: float) -> str:
    out = {
        "_meta": {
            "optimized": True,
            "composite_score": result.composite_score,
            "total_return_pct": result.total_return_pct,
            "sharpe_ratio": result.sharpe_ratio,
            "win_rate": result.win_rate,
            "profit_factor": result.profit_factor,
            "max_drawdown_pct": result.max_drawdown_pct,
            "total_trades": result.total_trades,
            "wf_consistency_pct": wf_consistency,
        },
        "strategy": {
            "min_score_buy": best_params["min_score_buy"],
            "min_score_sell": best_params["min_score_buy"],
            "rsi_oversold": best_params["rsi_oversold"],
            "rsi_overbought": best_params["rsi_overbought"],
            "bb_std": best_params["bb_std"],
        },
        "risk": {
            "stop_loss_atr_mult": best_params["stop_loss_atr_mult"],
            "take_profit_rr": best_params["take_profit_rr"],
        },
    }
    path = os.path.join(os.path.dirname(__file__), "optimized_config.json")
    with open(path, "w") as f:
        json.dump(out, f, indent=2)
    return path


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    console.print(Panel(
        "[bold white]⬡ PROFIT ENGINE — OPTIMISEUR[/]\n"
        f"[dim]{TOTAL_COMBOS} combinaisons × {len(SYMBOLS)} symboles\n"
        "Commission: 0.1% | Slippage: 0.05% | Capital de départ: $10,000[/]",
        box=box.DOUBLE, border_style="cyan"
    ))
    console.print()

    data_map = download_all()
    if not data_map:
        console.print("[red]Aucune donnée disponible.[/]")
        sys.exit(1)

    available = list(data_map.keys())
    total_candles = sum(len(df) for df in data_map.values())
    console.print(f"\n[dim]{len(available)} symboles · {total_candles:,} bougies totales[/]\n")

    optimizer = Optimizer(config, commission=0.001, slippage=0.0005)

    start = time.time()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=40),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        TextColumn("[dim]{task.fields[info]}[/]"),
        console=console,
        refresh_per_second=4,
    ) as progress:
        task = progress.add_task(
            f"Optimisation ({TOTAL_COMBOS} combos)...",
            total=TOTAL_COMBOS, info=""
        )

        def on_progress(i, total, params, score):
            info = (
                f"#{i:4d}  score={score:+.3f}  "
                f"MinSc={params.get('min_score_buy')}  "
                f"SL×{params.get('stop_loss_atr_mult')}  "
                f"R:R={params.get('take_profit_rr')}"
            )
            progress.update(task, completed=i, info=info)

        result = optimizer.run(available, data_map, progress_fn=on_progress)

    elapsed = time.time() - start
    console.print(f"\n[green]✓ Terminé en {elapsed:.1f}s "
                  f"({TOTAL_COMBOS * len(available) / elapsed:.0f} backtests/s)[/]\n")

    # Top results table
    print_top_table(result.top_results)
    console.print()

    # Walk-forward table
    if result.wf_windows:
        print_wf_table(result.wf_windows, result.wf_consistency, available[0])
        console.print()

    # Best config summary
    bp = result.best_params
    bm = result.best_metrics
    wf_col = "green" if result.wf_consistency >= 75 else "yellow" if result.wf_consistency >= 50 else "red"
    console.print(Panel(
        Text.from_markup(
            "[bold green]🏆 MEILLEURE CONFIGURATION[/]\n\n"
            f"[white]Score composite :[/] [cyan]{result.best_score:+.4f}[/]\n"
            f"[white]Rendement total :[/] {'[green]' if bm.total_return_pct > 0 else '[red]'}"
            f"{bm.total_return_pct:+.2f}%[/]\n"
            f"[white]Sharpe Ratio    :[/] {bm.sharpe_ratio:.3f}\n"
            f"[white]Sortino Ratio   :[/] {bm.sortino_ratio:.3f}\n"
            f"[white]Win Rate        :[/] {bm.win_rate:.1f}%\n"
            f"[white]Profit Factor   :[/] {bm.profit_factor:.3f}\n"
            f"[white]Max Drawdown    :[/] {bm.max_drawdown_pct:.2f}%\n"
            f"[white]Trades          :[/] {bm.total_trades}\n"
            f"[white]WF consistance  :[/] [{wf_col}]{result.wf_consistency:.0f}%[/]\n\n"
            "[bold]Paramètres optimaux :[/]\n"
            + "\n".join(f"  [cyan]{k:25s}[/] {v}" for k, v in bp.items())
        ),
        box=box.DOUBLE, border_style="green"
    ))

    cfg_path = save_config(bp, bm, result.wf_consistency)
    console.print(f"\n[green]✓ Config sauvegardée :[/] {cfg_path}")

    # Risk warning
    wf_ok = result.wf_consistency >= 75
    console.print(Panel(
        Text.from_markup(
            "[bold yellow]⚠ AVANT DE METTRE DE L'ARGENT RÉEL[/]\n\n"
            f"  Walk-forward consistance : [{wf_col}]{result.wf_consistency:.0f}%[/] "
            f"({'✅ BON' if wf_ok else '⚠ MOYEN — attendre plus de données'})\n\n"
            "  1. [white]Tester d'abord 2-4 semaines en PAPER TRADING avec la config optimisée[/]\n"
            "  2. [white]Vérifier que les résultats réels correspondent au backtest[/]\n"
            "  3. [white]Commencer avec MAX 5-10% de ton capital en live[/]\n"
            "  4. [white]Surveiller le drawdown — arrêter si dépasse 15%[/]\n\n"
            "  [dim]Les performances passées ne garantissent pas les performances futures.[/]"
        ),
        box=box.ROUNDED, border_style="yellow"
    ))

    console.print(
        "\n[dim]Pour appliquer les paramètres optimaux, modifier backend/.env :[/]\n"
        + "\n".join(f"  [cyan]{k.upper()}={v}[/]" for k, v in {
            "PAPER_TRADING": "true",
        }.items())
    )


if __name__ == "__main__":
    main()
