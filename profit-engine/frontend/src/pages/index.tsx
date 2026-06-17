import dynamic from 'next/dynamic';
import { useState } from 'react';
import { useWebSocket } from '../hooks/useWebSocket';
import SignalFeed from '../components/SignalFeed';
import Portfolio from '../components/Portfolio';
import Header from '../components/Header';
import Positions from '../components/Positions';
import TradeHistory from '../components/TradeHistory';

const Chart = dynamic(() => import('../components/Chart'), { ssr: false });

export default function Dashboard() {
  const { state, connected, toggleBot, closePosition } = useWebSocket();
  const [selected, setSelected] = useState('BTC/USDT');
  const [activeTab, setActiveTab] = useState<'signals' | 'positions' | 'history'>('signals');

  const allSymbols = [...new Set(state.signals.map(s => s.symbol))];
  const selectedSignal = state.signals.find(s => s.symbol === selected);

  return (
    <div className="h-screen bg-[#0d0d0d] text-white flex flex-col overflow-hidden font-sans">

      {/* ── Top Header ── */}
      <Header
        portfolio={state.portfolio}
        connected={connected}
        running={state.running}
        onToggle={toggleBot}
      />

      {/* ── Symbol Tabs ── */}
      <div className="flex-none flex items-center gap-1 px-4 py-1.5 border-b border-white/5 bg-[#0d0d0d] overflow-x-auto">
        {allSymbols.length === 0
          ? ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'SPY', 'QQQ'].map(s => (
              <SymbolTab key={s} symbol={s} active={selected === s} signal={null}
                         onClick={() => setSelected(s)} />
            ))
          : allSymbols.slice(0, 8).map(s => (
              <SymbolTab key={s} symbol={s} active={selected === s}
                         signal={state.signals.find(x => x.symbol === s) ?? null}
                         onClick={() => setSelected(s)} />
            ))}
        <div className="ml-auto flex-none text-xs text-white/20 font-mono pr-1">
          RSI · MACD · BB · EMA · ATR · Stoch · Patterns · S/R
        </div>
      </div>

      {/* ── Body ── */}
      <div className="flex flex-1 overflow-hidden">

        {/* ── Chart Column ── */}
        <div className="flex flex-col flex-1 min-w-0 border-r border-white/5">
          {/* Selected signal banner */}
          {selectedSignal && (
            <SignalBanner signal={selectedSignal} />
          )}
          <Chart symbol={selected} className="flex-1" />
          <StatusBar portfolio={state.portfolio} />
        </div>

        {/* ── Right Column ── */}
        <div className="w-[320px] xl:w-[380px] flex-none flex flex-col bg-[#111] overflow-hidden">

          {/* Portfolio Stats */}
          <Portfolio portfolio={state.portfolio} />

          {/* Tab selector */}
          <div className="flex border-b border-white/5 flex-none">
            {(['signals', 'positions', 'history'] as const).map(tab => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={`flex-1 py-2 text-xs font-medium transition-colors capitalize tracking-wide ${
                  activeTab === tab
                    ? 'text-white border-b border-[#00d4aa]'
                    : 'text-white/30 hover:text-white/60'
                }`}
              >
                {tab === 'signals' ? `Signaux (${state.signals.length})` :
                 tab === 'positions' ? `Positions (${Object.keys(state.positions).length})` :
                 `Historique (${state.closed_trades.length})`}
              </button>
            ))}
          </div>

          {/* Tab content */}
          <div className="flex-1 overflow-auto">
            {activeTab === 'signals' && <SignalFeed signals={state.signals} />}
            {activeTab === 'positions' && (
              <Positions positions={state.positions} onClose={closePosition} />
            )}
            {activeTab === 'history' && <TradeHistory trades={state.closed_trades} />}
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── Sub-components ── */

function SymbolTab({ symbol, active, signal, onClick }: {
  symbol: string;
  active: boolean;
  signal: any;
  onClick: () => void;
}) {
  const actionColor = signal?.action === 'BUY' ? 'text-[#00d4aa]' :
                      signal?.action === 'SELL' ? 'text-[#ff4d6d]' : 'text-white/40';
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-1.5 px-3 py-1 rounded text-xs font-mono transition-all whitespace-nowrap ${
        active
          ? 'bg-white/10 text-white'
          : 'text-white/40 hover:text-white/70 hover:bg-white/5'
      }`}
    >
      {signal && (
        <span className={`text-[10px] font-bold ${actionColor}`}>
          {signal.action === 'BUY' ? '▲' : signal.action === 'SELL' ? '▼' : '◆'}
        </span>
      )}
      {symbol}
      {signal && (
        <span className="text-[10px] text-white/30">{signal.score.toFixed(0)}</span>
      )}
    </button>
  );
}

function SignalBanner({ signal }: { signal: any }) {
  const isBuy = signal.action === 'BUY';
  const isSell = signal.action === 'SELL';
  const accentColor = isBuy ? '#00d4aa' : isSell ? '#ff4d6d' : '#f59e0b';
  const bg = isBuy ? 'bg-[#00d4aa]/5 border-[#00d4aa]/20' :
             isSell ? 'bg-[#ff4d6d]/5 border-[#ff4d6d]/20' :
             'bg-white/3 border-white/10';

  return (
    <div className={`flex-none flex items-center gap-4 px-4 py-2 border-b text-xs ${bg}`}>
      <span className="font-mono text-white/50">Signal actuel :</span>
      <span className="font-bold font-mono" style={{ color: accentColor }}>
        {signal.action}
      </span>
      <div className="flex items-center gap-1">
        <div className="w-20 h-1.5 bg-white/10 rounded-full overflow-hidden">
          <div
            className="h-full rounded-full transition-all"
            style={{ width: `${signal.score}%`, backgroundColor: accentColor }}
          />
        </div>
        <span className="font-mono text-white/40">{signal.score.toFixed(0)}/100</span>
      </div>
      <span className="font-mono text-white/60">{signal.price.toLocaleString()}</span>
      {signal.action !== 'HOLD' && (
        <>
          <span className="text-[#ff4d6d] font-mono">SL {signal.suggested_sl.toFixed(2)}</span>
          <span className="text-[#00d4aa] font-mono">TP {signal.suggested_tp.toFixed(2)}</span>
        </>
      )}
      <div className="ml-auto flex flex-wrap gap-1 max-w-xs">
        {signal.reasons.slice(0, 3).map((r: string, i: number) => (
          <span key={i} className="bg-white/5 text-white/40 px-1.5 py-0.5 rounded">{r}</span>
        ))}
      </div>
    </div>
  );
}

function StatusBar({ portfolio }: { portfolio: any }) {
  const pnlPos = portfolio.total_pnl >= 0;
  return (
    <div className="flex-none flex items-center gap-6 px-4 py-2 border-t border-white/5 bg-[#0d0d0d] text-xs font-mono text-white/30">
      <span>Capital <span className="text-white/60">${portfolio.equity.toLocaleString('fr-FR', { minimumFractionDigits: 2 })}</span></span>
      <span>P&L <span className={pnlPos ? 'text-[#00d4aa]' : 'text-[#ff4d6d]'}>
        {pnlPos ? '+' : ''}{portfolio.total_pnl.toFixed(2)} ({pnlPos ? '+' : ''}{portfolio.total_pnl_pct.toFixed(2)}%)
      </span></span>
      <span>DD <span className="text-[#f59e0b]">{portfolio.drawdown_pct.toFixed(2)}%</span></span>
      <span>Trades <span className="text-white/60">{portfolio.closed_trades}</span></span>
    </div>
  );
}
