import { Position } from '../lib/types';

interface PositionsProps {
  positions: Record<string, Position>;
  onClose: (symbol: string) => void;
}

export default function Positions({ positions, onClose }: PositionsProps) {
  const entries = Object.entries(positions);

  if (entries.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-40 gap-2">
        <span className="text-2xl opacity-20">◈</span>
        <span className="text-xs text-white/20">Aucune position ouverte</span>
      </div>
    );
  }

  return (
    <div className="flex flex-col divide-y divide-white/5">
      {entries.map(([symbol, pos]) => {
        const pnlPos = pos.unrealized_pnl >= 0;
        const curPrice = pos.current_price ?? pos.entry_price;
        const pnlPct = pos.entry_price > 0
          ? ((curPrice - pos.entry_price) / pos.entry_price * 100 * (pos.side === 'long' ? 1 : -1))
          : 0;

        return (
          <div key={symbol} className="px-3 py-3 hover:bg-white/[0.02] transition-colors">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded ${
                  pos.side === 'long' ? 'bg-[#00d4aa]/15 text-[#00d4aa]' : 'bg-[#ff4d6d]/15 text-[#ff4d6d]'
                }`}>
                  {pos.side === 'long' ? 'LONG' : 'SHORT'}
                </span>
                <span className="text-xs font-mono font-semibold text-white/80">{symbol}</span>
              </div>
              <button
                onClick={() => onClose(symbol)}
                className="text-[10px] text-white/30 hover:text-[#ff4d6d] transition-colors px-2 py-0.5 hover:bg-[#ff4d6d]/10 rounded"
              >
                Fermer
              </button>
            </div>

            <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-[10px] font-mono">
              <Row label="Entrée" value={`$${pos.entry_price.toLocaleString()}`} />
              <Row label="Actuel" value={`$${curPrice.toLocaleString()}`} />
              <Row label="Qté" value={pos.quantity.toFixed(4)} />
              <Row
                label="P&L"
                value={`${pnlPos ? '+' : ''}${pnlPct.toFixed(2)}%`}
                color={pnlPos ? '#00d4aa' : '#ff4d6d'}
              />
              <Row label="SL" value={`$${pos.sl.toFixed(2)}`} color="#ff4d6d" />
              <Row label="TP" value={`$${pos.tp.toFixed(2)}`} color="#00d4aa" />
            </div>

            <div className={`mt-2 text-right text-xs font-mono font-semibold ${pnlPos ? 'text-[#00d4aa]' : 'text-[#ff4d6d]'}`}>
              {pnlPos ? '+' : ''}${pos.unrealized_pnl.toFixed(2)}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function Row({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <>
      <span className="text-white/25">{label}</span>
      <span style={{ color: color ?? 'rgba(255,255,255,0.55)' }}>{value}</span>
    </>
  );
}
