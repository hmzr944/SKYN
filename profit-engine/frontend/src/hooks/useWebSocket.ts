import { useCallback, useEffect, useRef, useState } from 'react';
import { BotState, WSMessage } from '../lib/types';

const WS_URL = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000/ws';
const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

const EMPTY_STATE: BotState = {
  running: false,
  portfolio: {
    equity: 0, cash: 0, initial_capital: 0,
    total_pnl: 0, total_pnl_pct: 0,
    drawdown_pct: 0, win_rate: 0,
    open_positions: 0, closed_trades: 0,
  },
  signals: [],
  positions: {},
  closed_trades: [],
};

export function useWebSocket() {
  const [state, setState] = useState<BotState>(EMPTY_STATE);
  const [connected, setConnected] = useState(false);
  const ws = useRef<WebSocket | null>(null);

  const refetch = useCallback(() => {
    fetch(`${API_URL}/api/state`)
      .then(r => r.json())
      .then(data => setState(data as BotState))
      .catch(() => {});
  }, []);

  const connect = useCallback(() => {
    if (ws.current?.readyState === WebSocket.OPEN) return;
    const socket = new WebSocket(WS_URL);
    socket.onopen = () => setConnected(true);
    socket.onclose = () => {
      setConnected(false);
      setTimeout(connect, 3000);
    };
    socket.onerror = () => socket.close();
    socket.onmessage = (e: MessageEvent) => {
      try {
        const msg: WSMessage = JSON.parse(e.data);
        if (msg.type === 'init') {
          setState(msg.data as BotState);
        } else if (msg.type === 'signal') {
          const sig = msg.data;
          setState(prev => ({
            ...prev,
            portfolio: sig.portfolio ?? prev.portfolio,
            signals: [sig, ...prev.signals.filter((s: any) => s.symbol !== sig.symbol)].slice(0, 30),
          }));
        } else if (msg.type === 'position_opened' || msg.type === 'trade_closed') {
          refetch();
        }
      } catch {}
    };
    ws.current = socket;
  }, [refetch]);

  useEffect(() => {
    connect();
    return () => ws.current?.close();
  }, [connect]);

  const toggleBot = useCallback(async (running: boolean) => {
    await fetch(`${API_URL}/api/bot/${running ? 'start' : 'stop'}`, { method: 'POST' });
    setState(prev => ({ ...prev, running }));
  }, []);

  const closePosition = useCallback(async (symbol: string) => {
    await fetch(`${API_URL}/api/trade`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol, action: 'close' }),
    });
    setTimeout(refetch, 500);
  }, [refetch]);

  return { state, connected, toggleBot, closePosition };
}
