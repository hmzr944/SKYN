#!/usr/bin/env python3
"""
PRISM v33 — Dashboard Server
Usage : python3 dashboard_server.py [--port 5001]
Ouvrir  http://localhost:5001  dans le navigateur
"""
import argparse
import csv
import json
from pathlib import Path
from datetime import datetime

try:
    from flask import Flask, jsonify, send_file
    from flask_cors import CORS
except ImportError:
    print("pip install flask flask-cors")
    raise

BASE_DIR        = Path(__file__).parent
STATE_FILE      = BASE_DIR / "live_state_v33.json"
LOG_DIR         = BASE_DIR / "live_logs"
HTML_FILE       = BASE_DIR / "dashboard.html"
INITIAL_CAPITAL = 2500.0
BOT_ONLINE_S    = 90 * 60   # considère le bot "en ligne" si dernier run < 90 min

app = Flask(__name__)
CORS(app)


def _is_online(last_run_ts: str) -> bool:
    if not last_run_ts:
        return False
    try:
        dt = datetime.fromisoformat(last_run_ts)
        return (datetime.now() - dt).total_seconds() < BOT_ONLINE_S
    except Exception:
        return False


@app.route("/")
def index():
    return send_file(HTML_FILE)


@app.route("/api/state")
def api_state():
    if not STATE_FILE.exists():
        return jsonify({
            "equity": INITIAL_CAPITAL, "peak_equity": INITIAL_CAPITAL,
            "return_pct": 0.0, "drawdown_pct": 0.0,
            "total_trades": 0, "total_wins": 0, "total_pnl": 0.0, "win_rate": 0.0,
            "open_positions": [], "pending_entries": [],
            "n_open": 0, "n_pending": 0,
            "started_at": "", "last_run_ts": "", "online": False,
        })
    with open(STATE_FILE) as f:
        s = json.load(f)
    equity      = float(s.get("equity",      INITIAL_CAPITAL))
    peak        = float(s.get("peak_equity", equity))
    last_run_ts = s.get("last_run_ts", "")
    tw          = s.get("total_wins",   0)
    tt          = s.get("total_trades", 0)
    return jsonify({
        "equity":          round(equity, 2),
        "peak_equity":     round(peak, 2),
        "return_pct":      round((equity - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100, 2),
        "drawdown_pct":    round((peak - equity) / max(peak, 1e-10) * 100, 2),
        "total_trades":    tt,
        "total_wins":      tw,
        "total_pnl":       round(float(s.get("total_pnl", 0.0)), 2),
        "win_rate":        round(tw / max(tt, 1) * 100, 1),
        "open_positions":  list(s.get("open_positions",  {}).values()),
        "pending_entries": list(s.get("pending_entries", {}).values()),
        "n_open":          len(s.get("open_positions",  {})),
        "n_pending":       len(s.get("pending_entries", {})),
        "day_start_equity": round(float(s.get("day_start_equity", INITIAL_CAPITAL)), 2),
        "started_at":      s.get("started_at",  ""),
        "last_run_ts":     last_run_ts,
        "online":          _is_online(last_run_ts),
    })


@app.route("/api/trades")
def api_trades():
    rows = []
    for path in sorted(LOG_DIR.glob("live_trades_*.csv")):
        with open(path) as f:
            for row in csv.DictReader(f):
                rows.append(row)
    rows.sort(key=lambda r: r.get("exit_ts", ""), reverse=True)
    return jsonify(rows[:100])


@app.route("/api/equity-curve")
def api_equity_curve():
    pts = [{"ts": "Départ", "equity": INITIAL_CAPITAL}]
    for path in sorted(LOG_DIR.glob("live_trades_*.csv")):
        with open(path) as f:
            for row in csv.DictReader(f):
                try:
                    pts.append({
                        "ts":     row["exit_ts"][:16],
                        "equity": float(row["equity_after"]),
                    })
                except (KeyError, ValueError):
                    pass
    pts.sort(key=lambda r: r["ts"])
    return jsonify(pts)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5001)
    args = parser.parse_args()
    print(f"\n  Dashboard PRISM v33 → http://localhost:{args.port}\n")
    app.run(host="0.0.0.0", port=args.port, debug=False)
