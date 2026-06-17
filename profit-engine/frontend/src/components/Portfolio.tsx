import { PortfolioStats } from '../lib/types';

interface Props {
  portfolio: PortfolioStats;
}

export default function Portfolio({ portfolio }: Props) {
  const pnlPos = portfolio.total_pnl >= 0;
  const s = pnlPos ? '+' : '';

  const stats = [
    {
      label: 'Equity',
      value: `$${portfolio.equity.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,
      color: 'text-white/80',
    },
    {
      label: 'P&L',
      value: `${s}$${portfolio.total_pnl.toFixed(2)}`,
      sub: `${s}${portfolio.total_pnl_pct.toFixed(2)}%`,
      color: pnlPos ? 'text-[#00d4aa]' : 'text-[#ff4d6d]',
    },
    {
      label: 'Drawdown',
      value: `${portfolio.drawdown_pct.toFixed(2)}%`,
      color: portfolio.drawdown_pct > 8 ? 'text-[#ff4d6d]' : portfolio.drawdown_pct > 4 ? 'text-[#f59e0b]' : 'text-[#00d4aa]',
    },
    {
      label: 'Win Rate',
      value: `${portfolio.win_rate.toFixed(1)}%`,
      color: portfolio.win_rate >= 50 ? 'text-[#00d4aa]' : 'text-[#f59e0b]',
    },
  ];

  return (
    <div className="flex-none grid grid-cols-2 gap-px bg-white/5 border-b border-white/5">
      {stats.map(({ label, value, sub, color }) => (
        <div key={label} className="bg-[#111] px-3 py-2.5">
          <div className="text-[9px] font-mono text-white/25 uppercase tracking-widest mb-0.5">{label}</div>
          <div className={`text-sm font-mono font-semibold ${color} leading-tight`}>{value}</div>
          {sub && <div className={`text-[10px] font-mono ${color} opacity-60`}>{sub}</div>}
        </div>
      ))}
    </div>
  );
}
