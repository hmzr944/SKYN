import { PortfolioStats } from '../lib/types';

interface HeaderProps {
  portfolio: PortfolioStats;
  connected: boolean;
  running: boolean;
  onToggle: (running: boolean) => void;
}

export default function Header({ portfolio, connected, running, onToggle }: HeaderProps) {
  const pnlPos = portfolio.total_pnl >= 0;

  return (
    <div className="flex-none flex items-center gap-4 px-4 h-12 border-b border-white/5 bg-[#0a0a0a]">
      {/* Brand */}
      <div className="flex items-center gap-2 flex-none">
        <div className="w-5 h-5 rounded bg-[#00d4aa] flex items-center justify-center">
          <span className="text-[9px] font-black text-black">PE</span>
        </div>
        <span className="text-xs font-semibold tracking-widest text-white/60 uppercase">Profit Engine</span>
      </div>

      <div className="w-px h-5 bg-white/10 flex-none" />

      {/* Key metrics */}
      <div className="flex items-center gap-5 text-xs font-mono">
        <Metric label="Capital" value={`$${portfolio.equity.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`} />
        <Metric
          label="P&L"
          value={`${pnlPos ? '+' : ''}$${portfolio.total_pnl.toFixed(2)} (${pnlPos ? '+' : ''}${portfolio.total_pnl_pct.toFixed(2)}%)`}
          color={pnlPos ? '#00d4aa' : '#ff4d6d'}
        />
        <Metric
          label="Drawdown"
          value={`${portfolio.drawdown_pct.toFixed(2)}%`}
          color={portfolio.drawdown_pct > 8 ? '#ff4d6d' : portfolio.drawdown_pct > 4 ? '#f59e0b' : '#00d4aa'}
        />
        <Metric label="Win Rate" value={`${portfolio.win_rate.toFixed(1)}%`} />
        <Metric label="Trades" value={String(portfolio.closed_trades)} />
      </div>

      {/* Spacer */}
      <div className="flex-1" />

      {/* Connection + Bot toggle */}
      <div className="flex items-center gap-3 flex-none">
        <div className="flex items-center gap-1.5">
          <div className={`w-1.5 h-1.5 rounded-full ${connected ? 'bg-[#00d4aa] animate-pulse' : 'bg-white/20'}`} />
          <span className="text-[10px] font-mono text-white/30">{connected ? 'LIVE' : 'OFF'}</span>
        </div>

        <span className="text-[10px] font-mono text-[#f59e0b] bg-[#f59e0b]/10 px-2 py-0.5 rounded">
          PAPER
        </span>

        <button
          onClick={() => onToggle(running)}
          className={`px-3 py-1 rounded text-[11px] font-semibold tracking-wide transition-all ${
            running
              ? 'bg-[#ff4d6d]/15 text-[#ff4d6d] hover:bg-[#ff4d6d]/25 border border-[#ff4d6d]/30'
              : 'bg-[#00d4aa]/15 text-[#00d4aa] hover:bg-[#00d4aa]/25 border border-[#00d4aa]/30'
          }`}
        >
          {running ? '⏹ Stop' : '▶ Start'}
        </button>
      </div>
    </div>
  );
}

function Metric({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <span className="text-white/30">
      {label}{' '}
      <span className="font-medium" style={{ color: color ?? 'rgba(255,255,255,0.7)' }}>
        {value}
      </span>
    </span>
  );
}
