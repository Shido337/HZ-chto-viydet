import { useEffect, useRef } from 'react';
import { useTradingStore } from '../store/tradingStore';
import type { WsEvent } from '../types';

const WS_URL = `ws://${window.location.host}/ws`;
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
        case 'market_snapshot':
          store.setSnapshot(event.data);
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
