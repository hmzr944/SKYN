import dynamic from 'next/dynamic';
import { useState } from 'react';
import { useWebSocket } from '../hooks/useWebSocket';
import SignalFeed from '../components/SignalFeed';
import Portfolio from '../components/Portfolio';
import BotControls from '../components/BotControls';

const Chart = dynamic(() => import('../components/Chart'), { ssr: false });

export default function Dashboard() {
  const { state, connected, toggleBot, closePosition } = useWebSocket();
  const [selected, setSelected] = useState('BTC/USDT');

  const allSymbols = [...new Set(state.signals.map(s => s.symbol))];

  return (
    <div className="h-screen bg-black text-white flex flex-col overflow-hidden">
      {/* Header */}
      <header className="flex-none flex items-center justify-between px-4 py-2 border-b border-gray-800 bg-gray-950 h-12">
        <div className="flex items-center gap-4">
          <span className="font-bold text-base tracking-tight">
            <span className="text-green-400">⬡</span> PROFIT ENGINE
          </span>
          <div className="flex items-center gap-1">
            {allSymbols.slice(0, 7).map(sym => (
              <button
                key={sym}
                onClick={() => setSelected(sym)}
                className={`text-xs px-2 py-1 rounded font-mono transition-colors ${
                  selected === sym
                    ? 'bg-gray-700 text-white'
                    : 'text-gray-500 hover:text-white hover:bg-gray-800'
                }`}
              >
                {sym}
              </button>
            ))}
          </div>
        </div>
        <BotControls running={state.running} connected={connected} onToggle={toggleBot} />
      </header>

      {/* Body */}
      <div className="flex flex-1 overflow-hidden">
        {/* Chart */}
        <div className="flex flex-col flex-1 border-r border-gray-800 overflow-hidden">
          <Chart symbol={selected} className="flex-1" />
          <div className="flex-none px-4 py-1.5 border-t border-gray-800 bg-gray-950 flex items-center gap-6 text-xs font-mono text-gray-500">
            <span>Capital: <span className="text-white">${state.portfolio.equity.toLocaleString('fr-FR', { minimumFractionDigits: 2 })}</span></span>
            <span>P&L: <span className={state.portfolio.total_pnl >= 0 ? 'text-green-400' : 'text-red-400'}>
              {state.portfolio.total_pnl >= 0 ? '+' : ''}${state.portfolio.total_pnl.toFixed(2)} ({state.portfolio.total_pnl_pct.toFixed(2)}%)
            </span></span>
            <span>Positions: <span className="text-white">{state.portfolio.open_positions}</span></span>
            <span>Trades: <span className="text-white">{state.portfolio.closed_trades}</span></span>
            <span className="ml-auto">RSI · MACD · BB · EMA · ATR · Patterns · S/R</span>
          </div>
        </div>

        {/* Right panel */}
        <div className="w-80 xl:w-96 flex flex-col bg-gray-950 overflow-hidden">
          <div className="flex-none p-3 border-b border-gray-800 overflow-auto" style={{ maxHeight: '50%' }}>
            <div className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">Portfolio</div>
            <Portfolio
              portfolio={state.portfolio}
              positions={state.positions}
              trades={state.closed_trades}
              onClose={closePosition}
            />
          </div>
          <div className="flex-1 flex flex-col p-3 overflow-hidden min-h-0">
            <div className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3 flex-none">
              Signaux en temps réel
            </div>
            <div className="flex-1 overflow-auto">
              <SignalFeed signals={state.signals} />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
