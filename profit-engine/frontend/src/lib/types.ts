export interface RegimeInfo {
  regime: 'bull_trend' | 'bear_trend' | 'ranging' | 'breakout' | 'high_volatility';
  strategy: string;
  adx: number;
  atr_pct: number;
  trend: 'up' | 'down' | 'neutral';
  vol_surge: boolean;
}

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
  regime?: string;
  strategy?: string;
  adx?: number;
  atr_pct?: number;
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
  leverage: number;
  margin_required: number;
  liquidation_price: number;
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
  leverage: number;
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
  daily_pnl_pct: number;
}

export interface BotState {
  running: boolean;
  portfolio: PortfolioStats;
  signals: Signal[];
  regimes: Record<string, RegimeInfo>;
  positions: Record<string, Position>;
  closed_trades: Trade[];
}

export interface WSMessage {
  type: 'init' | 'signal' | 'position_opened' | 'trade_closed';
  data: any;
  ts: string;
}
