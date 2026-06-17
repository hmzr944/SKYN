export interface Signal {
  symbol: string;
  action: 'BUY' | 'SELL' | 'HOLD';
  score: number;
  confidence: 'HIGH' | 'MEDIUM' | 'LOW';
  reasons: string[];
  price: number;
  suggested_sl: number;
  suggested_tp: number;
  timestamp: string;
}

export interface Position {
  symbol: string;
  side: 'long' | 'short';
  entry_price: number;
  current_price: number;
  quantity: number;
  sl: number;
  tp: number;
  unrealized_pnl: number;
  entry_time: string;
  asset_type: 'crypto' | 'etf';
}

export interface Trade {
  symbol: string;
  side: string;
  entry_price: number;
  exit_price: number;
  quantity: number;
  pnl: number;
  pnl_pct: number;
  entry_time: string;
  exit_time: string;
  exit_reason: string;
}

export interface PortfolioStats {
  equity: number;
  cash: number;
  initial_capital: number;
  total_pnl: number;
  total_pnl_pct: number;
  drawdown_pct: number;
  win_rate: number;
  open_positions: number;
  closed_trades: number;
}

export interface BotState {
  running: boolean;
  portfolio: PortfolioStats;
  signals: Signal[];
  positions: Record<string, Position>;
  closed_trades: Trade[];
}

export interface WSMessage {
  type: 'init' | 'signal' | 'position_opened' | 'trade_closed';
  data: any;
  ts: string;
}
