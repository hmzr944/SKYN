import { Trade } from '../lib/types';

interface TradeHistoryProps {
  trades: Trade[];
}

export default function TradeHistory({ trades }: TradeHistoryProps) {
  if (trades.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-40 gap-2">
        <span className="text-2xl opacity-20">◇</span>
        <span className="text-xs text-white/20">Aucun trade fermé</span>
      </div>
    );
  }

  const sorted = [...trades].reverse();

  return (
    <div className="flex flex-col divide-y divide-white/5">
      {sorted.map((trade, idx) => {
        const pnlPos = trade.pnl >= 0;
        const exitLabel: Record<string, string> = {
          stop_loss: 'SL',
          take_profit: 'TP',
          trailing_stop: 'Trail',
          manual: 'Manuel',
          end_of_data: 'Fin',
        };

        return (
          <div key={idx} className="px-3 py-2.5 hover:bg-white/[0.02] transition-colors">
            <div className="flex items-center justify-between mb-1">
              <div className="flex items-center gap-1.5">
                <span className={`text-[9px] font-bold ${pnlPos ? 'text-[#00d4aa]' : 'text-[#ff4d6d]'}`}>
                  {pnlPos ? '▲' : '▼'}
                </span>
                <span className="text-xs font-mono text-white/70">{trade.symbol}</span>
                <span className="text-[9px] text-white/25 font-mono">
                  {trade.side === 'long' ? 'L' : 'S'}
                </span>
              </div>
              <span className={`text-xs font-mono font-semibold ${pnlPos ? 'text-[#00d4aa]' : 'text-[#ff4d6d]'}`}>
                {pnlPos ? '+' : ''}${trade.pnl.toFixed(2)}
              </span>
            </div>

            <div className="flex items-center justify-between text-[10px] font-mono text-white/25">
              <span>
                ${trade.entry_price.toFixed(2)} → ${trade.exit_price.toFixed(2)}
              </span>
              <div className="flex items-center gap-1.5">
                <span className="text-[9px] bg-white/5 px-1.5 py-0.5 rounded text-white/30">
                  {exitLabel[trade.exit_reason] ?? trade.exit_reason}
                </span>
                <span>{trade.pnl_pct >= 0 ? '+' : ''}{trade.pnl_pct.toFixed(2)}%</span>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
