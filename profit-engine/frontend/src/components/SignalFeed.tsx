import { Signal } from '../lib/types';

const ACTION: Record<string, string> = {
  BUY: 'text-green-400 bg-green-400/10 border-green-400/30',
  SELL: 'text-red-400 bg-red-400/10 border-red-400/30',
  HOLD: 'text-yellow-400 bg-yellow-400/10 border-yellow-400/30',
};
const CONF: Record<string, string> = {
  HIGH: 'text-green-300', MEDIUM: 'text-yellow-300', LOW: 'text-gray-500',
};

export default function SignalFeed({ signals }: { signals: Signal[] }) {
  if (!signals.length) {
    return (
      <div className="flex flex-col items-center justify-center h-32 text-gray-600 text-sm">
        <span className="text-2xl mb-2">⏳</span>En attente des signaux...
      </div>
    );
  }
  return (
    <div className="space-y-2">
      {signals.map((sig, i) => (
        <div key={`${sig.symbol}-${i}`}
             className="bg-gray-900/80 rounded-lg p-3 border border-gray-800 hover:border-gray-700 transition-colors">
          <div className="flex items-center justify-between mb-1.5">
            <span className="font-mono text-sm font-bold text-white">{sig.symbol}</span>
            <div className="flex items-center gap-2">
              <span className={`text-xs font-bold px-2 py-0.5 rounded border ${ACTION[sig.action]}`}>
                {sig.action}
              </span>
              <span className={`text-xs font-mono ${CONF[sig.confidence]}`}>{sig.score.toFixed(0)}%</span>
            </div>
          </div>
          <div className="flex justify-between text-xs text-gray-400 mb-1.5">
            <span>Prix: <span className="text-white font-mono">{sig.price.toLocaleString()}</span></span>
            <span className={CONF[sig.confidence]}>{sig.confidence}</span>
          </div>
          {sig.reasons.length > 0 && (
            <div className="flex flex-wrap gap-1 mb-1.5">
              {sig.reasons.slice(0, 3).map((r, j) => (
                <span key={j} className="text-xs bg-gray-800 text-gray-300 px-1.5 py-0.5 rounded">{r}</span>
              ))}
            </div>
          )}
          {sig.action !== 'HOLD' && (
            <div className="flex gap-4 text-xs font-mono">
              <span className="text-red-400">SL: {sig.suggested_sl.toLocaleString()}</span>
              <span className="text-green-400">TP: {sig.suggested_tp.toLocaleString()}</span>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
