#!/usr/bin/env python3
"""
Profit Engine — Aggressive Leveraged Optimizer
Run: python optimize_aggressive.py

Tests 2160 parameter combinations on 2 years of hourly BTC/ETH/SOL data
using Binance Futures simulation (dynamic leverage, 0.04% commission).
Saves best config to leveraged_config.json.
"""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.progress import (
    Progress, SpinnerColumn, TextColumn,
    BarColumn, TaskProgressColumn, TimeElapsedColumn,
)
from rich import box

from config import config
from backtester.aggressive_optimizer import (
    AggressiveOptimizer, AggOptResult, CRYPTO_SYMBOLS, TOTAL_COMBOS
)
from backtester.optimizer import fetch_data

console = Console()


# ---------------------------------------------------------------------------
# Data download
# ---------------------------------------------------------------------------

def download_all(symbols=CRYPTO_SYMBOLS) -> dict:
    data = {}
    console.print("[bold cyan]Downloading historical data (2y, 1h)...[/]\n")
    for sym in symbols:
        with console.status(f"  {sym}..."):
            df = fetch_data(sym, period="2y", interval="1h")
        if not df.empty:
            data[sym] = df
            console.print(
                f"  [green]✓[/] {sym:10s} — "
                f"{len(df):5,} candles "
                f"({df.index[0].date()} → {df.index[-1].date()})"
            )
        else:
            console.print(f"  [red]✗[/] {sym} — download failed")
    return data


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def print_top_table(top_results, n: int = 20) -> None:
    tbl = Table(
        title=f"[bold]Top {n} Configurations[/] (leveraged composite score)",
        box=box.ROUNDED,
        header_style="bold cyan",
        show_lines=False,
    )
    tbl.add_column("#",        width=4,  justify="right")
    tbl.add_column("Score",    width=8,  justify="right")
    tbl.add_column("Return",   width=10, justify="right")
    tbl.add_column("Lev.Ret",  width=10, justify="right")
    tbl.add_column("AvgLev",   width=8,  justify="right")
    tbl.add_column("Sharpe",   width=8,  justify="right")
    tbl.add_column("Win%",     width=7,  justify="right")
    tbl.add_column("PF",       width=6,  justify="right")
    tbl.add_column("MaxDD",    width=7,  justify="right")
    tbl.add_column("Trades",   width=7,  justify="right")
    tbl.add_column("Liqs",     width=6,  justify="right")
    tbl.add_column("MinSc",    width=6)
    tbl.add_column("SL×",      width=5)
    tbl.add_column("R:R",      width=5)
    tbl.add_column("RSI",      width=10)
    tbl.add_column("BB σ",     width=6)

    for idx, (params, res) in enumerate(top_results[:n], 1):
        sc      = res.composite_score
        sc_col  = "green" if sc > 1.5 else "yellow" if sc > 0.5 else "red"
        ret_col = "green" if res.total_return_pct > 0 else "red"
        lret_col = "green" if res.leveraged_return_pct > 0 else "red"
        dd_col  = "red" if res.max_drawdown_pct > 20 else "yellow" if res.max_drawdown_pct > 10 else "green"
        tbl.add_row(
            str(idx),
            f"[{sc_col}]{sc:+.3f}[/]",
            f"[{ret_col}]{res.total_return_pct:+.1f}%[/]",
            f"[{lret_col}]{res.leveraged_return_pct:+.1f}%[/]",
            f"{res.avg_leverage:.1f}x",
            f"{res.sharpe_ratio:.2f}",
            f"{res.win_rate:.1f}%",
            f"{res.profit_factor:.2f}",
            f"[{dd_col}]{res.max_drawdown_pct:.1f}%[/]",
            str(res.total_trades),
            str(res.liquidations),
            str(params.get("min_score_buy", "")),
            str(params.get("stop_loss_atr_mult", "")),
            str(params.get("take_profit_rr", "")),
            f"{params.get('rsi_oversold','')}/{params.get('rsi_overbought','')}",
            str(params.get("bb_std", "")),
        )
    console.print(tbl)


def print_wf_table(wf_windows, wf_consistency: float, symbol: str) -> None:
    tbl = Table(
        title=f"Walk-Forward ({symbol}) — out-of-sample validation",
        box=box.SIMPLE,
    )
    tbl.add_column("Window",   width=10)
    tbl.add_column("Return",   width=10, justify="right")
    tbl.add_column("Sharpe",   width=8,  justify="right")
    tbl.add_column("Win%",     width=7,  justify="right")
    tbl.add_column("AvgLev",   width=8,  justify="right")
    tbl.add_column("Trades",   width=8,  justify="right")
    tbl.add_column("Result",   width=14)

    for w in wf_windows:
        ret_col = "green" if w.profitable else "red"
        tbl.add_row(
            f"Period {w.period}",
            f"[{ret_col}]{w.total_return_pct:+.2f}%[/]",
            f"{w.sharpe_ratio:.2f}",
            f"{w.win_rate:.1f}%",
            f"{w.avg_leverage:.1f}x",
            str(w.total_trades),
            f"[{ret_col}]{'Profitable' if w.profitable else 'Loss'}[/]",
        )
    tbl.add_section()
    cons_col = "green" if wf_consistency >= 75 else "yellow" if wf_consistency >= 50 else "red"
    tbl.add_row(
        "CONSISTENCY", "", "", "", "", "",
        f"[{cons_col}]{wf_consistency:.0f}% profitable windows[/]",
    )
    console.print(tbl)


# ---------------------------------------------------------------------------
# Save config
# ---------------------------------------------------------------------------

def save_config(best_params: dict, result, wf_consistency: float) -> str:
    out = {
        "_meta": {
            "optimized": True,
            "optimizer": "aggressive_leveraged",
            "composite_score": result.composite_score,
            "total_return_pct": result.total_return_pct,
            "leveraged_return_pct": result.leveraged_return_pct,
            "avg_leverage": result.avg_leverage,
            "sharpe_ratio": result.sharpe_ratio,
            "win_rate": result.win_rate,
            "profit_factor": result.profit_factor,
            "max_drawdown_pct": result.max_drawdown_pct,
            "total_trades": result.total_trades,
            "liquidations": result.liquidations,
            "daily_loss_stops": result.daily_loss_stops,
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
            "risk_per_trade_pct": 0.02,
        },
        "leverage": {
            "enabled": True,
            "mode": "cross",
            "score_to_leverage": {"60": 2, "70": 3, "80": 5, "90": 8},
            "max_leverage": 10,
            "max_positions": 3,
            "daily_loss_limit_pct": 0.10,
        },
    }
    path = os.path.join(os.path.dirname(__file__), "leveraged_config.json")
    with open(path, "w") as f:
        json.dump(out, f, indent=2)
    return path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    console.print(Panel(
        "[bold white]PROFIT ENGINE — AGGRESSIVE LEVERAGED OPTIMIZER[/]\n"
        f"[dim]{TOTAL_COMBOS} combinations x {len(CRYPTO_SYMBOLS)} crypto symbols\n"
        "Commission: 0.04% (futures taker) | Slippage: 0.05% | Capital: $10,000\n"
        "Dynamic leverage: score 60→2x | 70→3x | 80→5x | 90→8x[/]",
        box=box.DOUBLE,
        border_style="cyan",
    ))
    console.print()

    data_map = download_all()
    if not data_map:
        console.print("[red]No data available. Exiting.[/]")
        sys.exit(1)

    available = list(data_map.keys())
    total_candles = sum(len(df) for df in data_map.values())
    console.print(
        f"\n[dim]{len(available)} symbols · {total_candles:,} total candles[/]\n"
    )

    optimizer = AggressiveOptimizer(config, commission=0.0004, slippage=0.0005)

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
            f"Optimizing ({TOTAL_COMBOS} combos)...",
            total=TOTAL_COMBOS,
            info="",
        )

        def on_progress(i, total, params, score):
            info = (
                f"#{i:4d}  score={score:+.3f}  "
                f"MinSc={params.get('min_score_buy')}  "
                f"SL×{params.get('stop_loss_atr_mult')}  "
                f"R:R={params.get('take_profit_rr')}"
            )
            progress.update(task, completed=i, info=info)

        result: AggOptResult = optimizer.run(available, data_map, progress_fn=on_progress)

    elapsed = time.time() - start
    console.print(
        f"\n[green]Done in {elapsed:.1f}s "
        f"({TOTAL_COMBOS * len(available) / elapsed:.0f} backtests/s)[/]\n"
    )

    print_top_table(result.top_results)
    console.print()

    if result.wf_windows:
        print_wf_table(result.wf_windows, result.wf_consistency, available[0])
        console.print()

    bp  = result.best_params
    bm  = result.best_metrics
    wf_col = (
        "green" if result.wf_consistency >= 75
        else "yellow" if result.wf_consistency >= 50
        else "red"
    )

    console.print(Panel(
        Text.from_markup(
            "[bold green]BEST CONFIGURATION (Leveraged)[/]\n\n"
            f"[white]Composite Score    :[/] [cyan]{result.best_score:+.4f}[/]\n"
            f"[white]Total Return       :[/] "
            f"{'[green]' if bm.total_return_pct > 0 else '[red]'}"
            f"{bm.total_return_pct:+.2f}%[/]\n"
            f"[white]Leveraged Return   :[/] "
            f"{'[green]' if bm.leveraged_return_pct > 0 else '[red]'}"
            f"{bm.leveraged_return_pct:+.2f}%[/]\n"
            f"[white]Avg Leverage       :[/] {bm.avg_leverage:.1f}x\n"
            f"[white]Sharpe Ratio       :[/] {bm.sharpe_ratio:.3f}\n"
            f"[white]Sortino Ratio      :[/] {bm.sortino_ratio:.3f}\n"
            f"[white]Win Rate           :[/] {bm.win_rate:.1f}%\n"
            f"[white]Profit Factor      :[/] {bm.profit_factor:.3f}\n"
            f"[white]Max Drawdown       :[/] {bm.max_drawdown_pct:.2f}%\n"
            f"[white]Trades             :[/] {bm.total_trades}\n"
            f"[white]Liquidations       :[/] {bm.liquidations}\n"
            f"[white]Daily Loss Stops   :[/] {bm.daily_loss_stops}\n"
            f"[white]WF Consistency     :[/] [{wf_col}]{result.wf_consistency:.0f}%[/]\n\n"
            "[bold]Optimal Parameters:[/]\n"
            + "\n".join(f"  [cyan]{k:25s}[/] {v}" for k, v in bp.items())
        ),
        box=box.DOUBLE,
        border_style="green",
    ))

    cfg_path = save_config(bp, bm, result.wf_consistency)
    console.print(f"\n[green]Config saved:[/] {cfg_path}")

    wf_ok = result.wf_consistency >= 75
    console.print(Panel(
        Text.from_markup(
            "[bold yellow]RISK WARNING — LEVERAGED TRADING[/]\n\n"
            f"  WF Consistency: [{wf_col}]{result.wf_consistency:.0f}%[/] "
            f"({'GOOD' if wf_ok else 'MARGINAL — wait for more data'})\n\n"
            "  1. [white]Run 2-4 weeks paper trading on Binance Futures testnet first[/]\n"
            "  2. [white]Start with MAX 5% of real capital[/]\n"
            "  3. [white]Verify live liquidations stay near zero before scaling[/]\n"
            "  4. [white]Daily loss limit is hardcoded at -10% — respect it[/]\n\n"
            "  [dim]Past performance does not guarantee future results.[/]"
        ),
        box=box.ROUNDED,
        border_style="yellow",
    ))


if __name__ == "__main__":
    main()
