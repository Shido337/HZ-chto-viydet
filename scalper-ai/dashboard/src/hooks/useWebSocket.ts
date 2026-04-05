import { useEffect, useRef } from 'react';
import { useTradingStore } from '../store/tradingStore';
import type { WsEvent } from '../types';

const WS_URL = `ws://127.0.0.1:9000/ws`;
const RECONNECT_DELAY = 3000;

export function useWebSocket(): void {
  const wsRef = useRef<WebSocket | null>(null);
  const store = useTradingStore();

  useEffect(() => {
    let alive = true;

    function connect() {
      if (!alive) return;
      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onopen = () => store.setWsConnected(true);
      ws.onclose = () => {
        store.setWsConnected(false);
        if (alive) setTimeout(connect, RECONNECT_DELAY);
      };
      ws.onerror = () => ws.close();
      ws.onmessage = (e) => {
        const event: WsEvent = JSON.parse(e.data);
        handleEvent(event);
      };
    }

    function handleEvent(event: WsEvent) {
      switch (event.type) {
        case 'init_state': {
          const { symbols, balance, daily_pnl, mode, regimes } = event.data;
          store.setSymbols(symbols);
          store.setBalance(balance, daily_pnl);
          store.setMode(mode);
          for (const [sym, reg] of Object.entries(regimes)) {
            store.setRegime(sym, reg);
          }
          // Auto-select first symbol if current not in list
          const current = useTradingStore.getState().selectedSymbol;
          if (!symbols.includes(current) && symbols.length > 0) {
            store.setSelectedSymbol(symbols[0]);
          }
          // Restore session trades from DB so stats survive dashboard refresh
          const sessionStart = event.data.started_at || '';
          fetch('/api/trades?limit=500')
            .then((r) => r.json())
            .then((rows: Array<{ symbol: string; direction: string; pnl: number; exit_reason: string; closed_at: string | null }>) => {
              const st = useTradingStore.getState();
              if (st.trades.length === 0 && rows.length > 0) {
                const cutoff = sessionStart ? new Date(sessionStart).getTime() : 0;
                const sessionTrades = cutoff
                  ? rows.filter((r) => r.closed_at && new Date(r.closed_at).getTime() >= cutoff)
                  : rows;
                for (const r of sessionTrades.reverse()) {
                  st.addTrade({ symbol: r.symbol, direction: r.direction as 'LONG' | 'SHORT', pnl: r.pnl, reason: r.exit_reason });
                }
              }
            })
            .catch(() => {});
          break;
        }
        case 'market_snapshot':
          store.setSnapshot(event.data);
          break;
        case 'kline_update':
          store.updateKline(
            event.data.symbol,
            event.data.tf,
            event.data.candle,
          );
          break;
        case 'signal_new':
          store.addSignal(event.data);
          break;
        case 'signal_expired':
          store.removeSignal(event.data.id);
          break;
        case 'position_opened':
          store.setPosition(event.data);
          break;
        case 'position_updated':
          store.setPosition(event.data);
          break;
        case 'trade_closed':
          store.addTrade(event.data);
          store.removePosition(event.data.symbol);
          break;
        case 'pending_order_placed':
          store.setPendingOrder(event.data);
          break;
        case 'pending_order_cancelled':
          store.removePendingOrder(event.data.symbol);
          break;
        case 'balance_update':
          store.setBalance(event.data.balance, event.data.daily_pnl);
          break;
        case 'regime_update':
          store.setRegime(event.data.symbol, event.data.regime);
          break;
        case 'error':
          console.error('[WS]', event.data.message);
          break;
      }
    }

    connect();
    return () => {
      alive = false;
      wsRef.current?.close();
    };
  }, []);
}
