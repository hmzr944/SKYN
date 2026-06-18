#!/bin/bash
# SKYN v15 APEX — Démarrage complet
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$DIR/backend"

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║        SKYN v15 APEX — Bot Trading       ║"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "  Dashboard : http://localhost:8765"
echo "  API       : http://localhost:8765/api"
echo ""
echo "  1. Ouvrez http://localhost:8765 dans votre navigateur"
echo "  2. Cliquez 'Démarrer bot' pour activer le scanning automatique"
echo "  3. Lancez un backtest (onglet Backtest) pour valider la stratégie"
echo "  4. Utilisez l'onglet Scanner pour un scan manuel immédiat"
echo ""
echo "  ⚡ Le bot scanne automatiquement toutes les heures"
echo "  📊 Les positions sont gérées en paper trading (simulation)"
echo "  🛡️  Circuit breaker: arrêt si -12% dans la journée"
echo ""

cd "$BACKEND"
python -m uvicorn apex_server:app --host 0.0.0.0 --port 8765 --log-level info
