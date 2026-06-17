#!/usr/bin/env python3
"""
Profit Engine — Entraînement ML
Lance: python train.py

Entraîne un modèle XGBoost par symbole sur 2 ans de données réelles (1h).
Target : prédire si le prix monte de +2% avant de tomber de -1% (R:R 1:2 natif).
Sauvegarde les modèles dans backend/models/.
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

from backtester.optimizer import fetch_data
from engine.ml.trainer import train_symbol, save_models

console = Console()

SYMBOLS = ["BTC-USD", "ETH-USD", "SOL-USD", "SPY", "QQQ"]
MODELS_DIR = os.path.join(os.path.dirname(__file__), "models")

# Paramètres ML
TP_PCT  = 0.02   # +2% pour un BUY
SL_PCT  = 0.01   # -1% stop → R:R 2:1
MAX_BARS = 48    # fenêtre max de 48h pour atteindre TP/SL


def main():
    console.print(Panel(
        "[bold white]⬡ PROFIT ENGINE — ENTRAÎNEMENT ML[/]\n"
        "[dim]XGBoost | 80+ features | 2 ans données réelles\n"
        f"Target : +{TP_PCT*100:.0f}% avant -{SL_PCT*100:.0f}% dans {MAX_BARS}h | R:R {TP_PCT/SL_PCT:.0f}:1[/]",
        box=box.DOUBLE, border_style="cyan"
    ))
    console.print()

    # Téléchargement
    console.print("[bold cyan]📥 Téléchargement données (2 ans, 1h)...[/]\n")
    data = {}
    for sym in SYMBOLS:
        with console.status(f"  {sym}..."):
            df = fetch_data(sym, period="2y", interval="1h")
        if not df.empty:
            data[sym] = df
            console.print(f"  [green]✓[/] {sym:10s} — {len(df):5,} bougies")
        else:
            console.print(f"  [red]✗[/] {sym} — échec")

    console.print()

    # Entraînement
    console.print("[bold cyan]🧠 Entraînement XGBoost...[/]\n")
    bundles = {}
    results = []
    start = time.time()

    for sym, df in data.items():
        with console.status(f"  {sym} — feature engineering + training..."):
            t0 = time.time()
            bundle = train_symbol(df, sym, tp_pct=TP_PCT, sl_pct=SL_PCT, max_bars=MAX_BARS)
            elapsed = time.time() - t0

        if bundle is None:
            console.print(f"  [red]✗[/] {sym} — échec entraînement")
            continue

        m = bundle.train_metrics
        acc_col = "green" if m["accuracy"] >= 0.58 else "yellow" if m["accuracy"] >= 0.52 else "red"
        prec_col = "green" if m["precision"] >= 0.60 else "yellow" if m["precision"] >= 0.52 else "red"
        console.print(
            f"  [green]✓[/] {sym:10s} "
            f"acc=[{acc_col}]{m['accuracy']:.1%}[/] "
            f"prec=[{prec_col}]{m['precision']:.1%}[/] "
            f"recall={m['recall']:.1%} "
            f"f1={m['f1']:.1%} "
            f"| {m['n_train']:,}+{m['n_val']:,} samples "
            f"| {elapsed:.1f}s"
        )
        bundles[sym] = bundle
        results.append((sym, m))

    elapsed_total = time.time() - start
    console.print(f"\n[green]✓ Entraînement terminé en {elapsed_total:.1f}s[/]\n")

    if not bundles:
        console.print("[red]Aucun modèle entraîné.[/]")
        sys.exit(1)

    # Table récap
    tbl = Table(title="Résultats d'entraînement", box=box.ROUNDED, header_style="bold cyan")
    tbl.add_column("Symbole", width=10)
    tbl.add_column("Accuracy", justify="right")
    tbl.add_column("Précision", justify="right")
    tbl.add_column("Recall", justify="right")
    tbl.add_column("F1", justify="right")
    tbl.add_column("Taux signal", justify="right")
    tbl.add_column("Samples", justify="right")

    for sym, m in results:
        acc_c = "green" if m["accuracy"] >= 0.58 else "yellow"
        pre_c = "green" if m["precision"] >= 0.60 else "yellow"
        tbl.add_row(
            sym,
            f"[{acc_c}]{m['accuracy']:.1%}[/]",
            f"[{pre_c}]{m['precision']:.1%}[/]",
            f"{m['recall']:.1%}",
            f"{m['f1']:.1%}",
            f"{m['pos_rate']:.1%}",
            f"{m['n_train']+m['n_val']:,}",
        )
    console.print(tbl)
    console.print()

    # Sauvegarde
    save_models(bundles, MODELS_DIR)
    console.print(f"[green]✓ {len(bundles)} modèles sauvegardés dans :[/] {MODELS_DIR}")
    console.print()

    # Interprétation
    avg_prec = sum(m["precision"] for _, m in results) / len(results)
    avg_acc  = sum(m["accuracy"] for _, m in results) / len(results)

    quality = "🟢 BON" if avg_prec >= 0.60 else "🟡 MOYEN" if avg_prec >= 0.52 else "🔴 FAIBLE"
    console.print(Panel(
        f"[bold]Précision moyenne : {avg_prec:.1%} — {quality}[/]\n\n"
        f"[white]Avec une précision de {avg_prec:.1%} et un R:R 2:1 :[/]\n"
        f"  Breakeven théorique : 33% de précision\n"
        f"  Edge estimé         : +{(avg_prec - 0.33) * 100:.1f}% au-dessus du seuil\n\n"
        "[dim]Lance maintenant : python optimize.py pour backtester avec le ML[/]",
        box=box.ROUNDED, border_style="green" if avg_prec >= 0.58 else "yellow"
    ))


if __name__ == "__main__":
    main()
