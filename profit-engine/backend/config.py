import os
from dataclasses import dataclass, field
from typing import Dict, List
from dotenv import load_dotenv

load_dotenv()


@dataclass
class ExchangeConfig:
    name: str = "binance"
    api_key: str = field(default_factory=lambda: os.getenv("EXCHANGE_API_KEY", ""))
    api_secret: str = field(default_factory=lambda: os.getenv("EXCHANGE_API_SECRET", ""))
    paper_trading: bool = field(default_factory=lambda: os.getenv("PAPER_TRADING", "true").lower() == "true")
    futures: bool = True
    leverage: int = 5


@dataclass
class LeverageConfig:
    enabled: bool = True
    mode: str = "cross"  # "cross" or "isolated"
    score_to_leverage: Dict[int, int] = field(default_factory=lambda: {
        60: 2,
        70: 3,
        80: 5,
        90: 8,
    })
    max_leverage: int = 10
    max_positions: int = 3
    risk_per_trade_pct: float = 0.02   # 2% per trade
    daily_loss_limit_pct: float = 0.10  # stop all trading if -10% in a day


@dataclass
class RiskConfig:
    risk_per_trade_pct: float = 0.02
    stop_loss_atr_mult: float = 1.0
    take_profit_rr: float = 2.0
    max_open_positions: int = 3
    max_drawdown_pct: float = 0.10
    trailing_stop_atr_mult: float = 0.8


@dataclass
class StrategyConfig:
    rsi_period: int = 14
    rsi_oversold: float = 30.0
    rsi_overbought: float = 70.0
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal_period: int = 9
    bb_period: int = 20
    bb_std: float = 2.0
    atr_period: int = 14
    ema_short: int = 9
    ema_medium: int = 21
    ema_long: int = 50
    ema_trend: int = 200
    min_score_buy: float = 60.0
    min_score_sell: float = 60.0
    timeframe: str = "1h"
    lookback: int = 200


@dataclass
class AppConfig:
    exchange: ExchangeConfig = field(default_factory=ExchangeConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    leverage: LeverageConfig = field(default_factory=LeverageConfig)
    crypto_symbols: List[str] = field(default_factory=lambda:
        os.getenv("CRYPTO_SYMBOLS", "BTC/USDT,ETH/USDT,SOL/USDT").split(","))
    etf_symbols: List[str] = field(default_factory=lambda:
        os.getenv("ETF_SYMBOLS", "SPY,QQQ,NVDA").split(","))
    initial_capital: float = float(os.getenv("INITIAL_CAPITAL", "10000"))
    api_host: str = os.getenv("API_HOST", "0.0.0.0")
    api_port: int = int(os.getenv("API_PORT", "8000"))


config = AppConfig()
