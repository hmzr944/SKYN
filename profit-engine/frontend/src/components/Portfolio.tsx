import { PortfolioStats, Position, Trade } from '../lib/types';

interface Props {
  portfolio: PortfolioStats;
  positions: Record<string, Position>;
  trades: Trade[];
  onClose: (symbol: string) => void;
}

export default function Portfolio({ portfolio, positions, trades, onClose }: Props) {
  const pnlColor = portfolio.total_pnl >= 0 ? 'text-green-400' : 'text-red-400';
  const sign = portfolio.total_pnl >= 0 ? '+' : '';

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-2">
        {[
          { label: 'Equity', value: `$${portfolio.equity.toLocaleString('fr-FR', { minimumFractionDigits: 2 })}`, color: 'text-white' },
          { label: 'P&L Total', value: `${sign}$${portfolio.total_pnl.toFixed(2)} (${sign}${portfolio.total_pnl_pct.toFixed(2)}%)`, color: pnlColor },
          { label: 'Drawdown', value: `${portfolio.drawdown_pct.toFixed(2)}%`, color: portfolio.drawdown_pct > 5 ? 'text-red-400' : 'text-yellow-400' },
          { label: 'Win Rate', value: `${portfolio.win_rate.toFixed(1)}%`, color: portfolio.win_rate >= 50 ? 'text-green-400' : 'text-red-400' },
        ].map(({ label, value, color }) => (
          <div key={label} className="bg-gray-900 rounded-lg p-2.5 border border-gray-800">
            <div className="text-xs text-gray-500 mb-0.5">{label}</div>
            <div className={`text-sm font-mono font-bold ${color} truncate`}>{value}</div>
          </div>
        ))}
      </div>

      <div>
        <div className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
          Positions ({Object.keys(positions).length})
        </div>
        {Object.keys(positions).length === 0 ? (
          <p className="text-xs text-gray-600 py-1">Aucune position ouverte</p>
        ) : (
          <div className="space-y-1.5">
            {Object.entries(positions).map(([sym, pos]) => (
              <div key={sym} className="bg-gray-900 rounded p-2.5 border border-gray-800">
                <div className="flex justify-between items-start mb-1">
                  <div>
                    <span className="font-mono text-xs font-bold text-white">{sym}</span>
                    <span className="text-xs text-gray-500 ml-1">{pos.asset_type}</span>
                  </div>
                  <button
                    onClick={() => onClose(sym)}
                    className="text-xs text-red-400 border border-red-400/20 px-1.5 py-0.5 rounded hover:bg-red-400/10 transition-colors"
                  >
                    Fermer
                  </button>
                </div>
                <div className="text-xs text-gray-400">
                  {pos.quantity.toFixed(4)} @ <span className="font-mono text-gray-300">{pos.entry_price.toLocaleString()}</span>
                </div>
                <div className="flex gap-3 text-xs mt-1">
                  <span className="text-red-400 font-mono">SL {pos.sl.toLocaleString()}</span>
                  <span className="text-green-400 font-mono">TP {pos.tp.toLocaleString()}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div>
        <div className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
          Derniers trades
        </div>
        {trades.length === 0 ? (
          <p className="text-xs text-gray-600 py-1">Aucun trade fermé</p>
        ) : (
          <div className="space-y-1">
            {[...trades].reverse().slice(0, 8).map((t, i) => {
              const c = t.pnl >= 0 ? 'text-green-400' : 'text-red-400';
              const s = t.pnl >= 0 ? '+' : '';
              return (
                <div key={i} className="flex items-center justify-between text-xs py-1 border-b border-gray-800/50 last:border-0">
                  <span className="font-mono text-gray-300 w-20 truncate">{t.symbol}</span>
                  <span className="text-gray-600 text-center flex-1">{t.exit_reason}</span>
                  <span className={`font-mono ${c}`}>{s}{t.pnl.toFixed(2)} ({s}{t.pnl_pct.toFixed(1)}%)</span>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
