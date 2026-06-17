import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel
from rich.text import Text
from rich import box
from datetime import datetime

from config import config
from engine.core import ProfitEngine

console = Console()


def _c(v: float) -> str:
    return "green" if v >= 0 else "red"


def build_display(engine: ProfitEngine) -> Layout:
    st = engine.get_state()
    pf = st["portfolio"]
    signals = st["signals"]
    positions = st["positions"]
    trades = st["closed_trades"]

    header = Panel(
        Text.from_markup(
            f"[bold white]⬡ PROFIT ENGINE[/]  "
            f"[cyan]${pf.get('equity', 0):,.2f}[/]  "
            f"[{_c(pf.get('total_pnl', 0))}]P&L {pf.get('total_pnl', 0):+,.2f} "
            f"({pf.get('total_pnl_pct', 0):+.2f}%)[/]  "
            f"[yellow]DD {pf.get('drawdown_pct', 0):.1f}%[/]  "
            f"[white]WR {pf.get('win_rate', 0):.0f}%[/]  "
            f"[{'green' if engine.running else 'red'}]"
            f"{'● RUNNING' if engine.running else '● STOPPED'}[/]  "
            f"[dim]{datetime.now().strftime('%H:%M:%S')}[/]"
        ),
        box=box.MINIMAL,
    )

    sig_tbl = Table(box=box.SIMPLE, header_style="bold magenta", padding=(0, 1))
    sig_tbl.add_column("Symbole", style="cyan", width=12)
    sig_tbl.add_column("Action", width=8)
    sig_tbl.add_column("Score", width=7)
    sig_tbl.add_column("Conf.", width=8)
    sig_tbl.add_column("Prix", width=14)
    sig_tbl.add_column("Raisons", width=45)
    for s in signals[:14]:
        act = s.get("action", "HOLD")
        col = "green" if act == "BUY" else "red" if act == "SELL" else "yellow"
        conf = s.get("confidence", "LOW")
        cc = "green" if conf == "HIGH" else "yellow" if conf == "MEDIUM" else "dim"
        r = ", ".join(s.get("reasons", [])[:2])
        sig_tbl.add_row(
            s.get("symbol", ""),
            f"[{col}]{act}[/]",
            f"[{col}]{s.get('score', 0):.0f}[/]",
            f"[{cc}]{conf}[/]",
            f"{s.get('price', 0):.4f}",
            f"[dim]{r}[/]",
        )

    pos_tbl = Table(box=box.SIMPLE, header_style="bold blue", padding=(0, 1))
    pos_tbl.add_column("Symbole", style="cyan")
    pos_tbl.add_column("Type")
    pos_tbl.add_column("Entrée")
    pos_tbl.add_column("SL")
    pos_tbl.add_column("TP")
    for sym, pos in positions.items():
        pos_tbl.add_row(
            sym, pos.get("asset_type", ""),
            f"{pos.get('entry_price', 0):.4f}",
            f"[red]{pos.get('sl', 0):.4f}[/]",
            f"[green]{pos.get('tp', 0):.4f}[/]",
        )

    tr_tbl = Table(box=box.SIMPLE, header_style="bold yellow", padding=(0, 1))
    tr_tbl.add_column("Symbole", style="cyan")
    tr_tbl.add_column("P&L")
    tr_tbl.add_column("P&L%")
    tr_tbl.add_column("Raison")
    for t in list(reversed(trades))[:8]:
        pnl = t.get("pnl", 0)
        c = _c(pnl)
        tr_tbl.add_row(
            t.get("symbol", ""),
            f"[{c}]{pnl:+.2f}[/]",
            f"[{c}]{t.get('pnl_pct', 0):+.2f}%[/]",
            t.get("exit_reason", ""),
        )

    layout = Layout()
    layout.split_column(
        Layout(header, size=3),
        Layout(name="body"),
    )
    layout["body"].split_row(
        Layout(Panel(sig_tbl, title="[bold]Signaux temps réel"), ratio=2),
        Layout(name="right"),
    )
    layout["right"].split_column(
        Layout(Panel(pos_tbl, title="[bold]Positions")),
        Layout(Panel(tr_tbl, title="[bold]Trades")),
    )
    return layout


async def main():
    console.print("[bold cyan]⬡ PROFIT ENGINE[/] — Démarrage...", justify="center")
    engine = ProfitEngine(config)
    try:
        with Live(build_display(engine), refresh_per_second=1, screen=True) as live:
            while True:
                await engine.run_once()
                live.update(build_display(engine))
                await asyncio.sleep(60)
    except KeyboardInterrupt:
        pass
    finally:
        await engine.close()
        console.print("[yellow]Bot arrêté.[/]")


if __name__ == "__main__":
    asyncio.run(main())
