import { create } from 'zustand';
import type {
  Candle,
  MarketSnapshot,
  MLStats,
  PendingOrder,
  Position,
  Signal,
  Trade,
} from '../types';

interface TradingState {
  /* data */
  mode: 'paper' | 'live';
  balance: number;
  dailyPnl: number;
  selectedSymbol: string;
  symbols: string[];
  regimes: Record<string, string>;
  snapshots: Record<string, MarketSnapshot>;
  signals: Signal[];
  positions: Position[];
  pendingOrders: PendingOrder[];
  trades: Trade[];
  mlStats: MLStats;
  wsConnected: boolean;
  settingsOpen: boolean;
  tradeHistoryOpen: boolean;
  sizeMode: 'FIXED' | 'ADAPTIVE' | 'PERCENT';
  fixedAmount: number;
  adaptiveBase: number;
  percentValue: number;

  /* derived */
  winRate: () => number;
  profitFactor: () => number;
  totalTrades: () => number;

  /* actions */
  setMode: (m: 'paper' | 'live') => void;
  setBalance: (b: number, pnl: number) => void;
  setSelectedSymbol: (s: string) => void;
  setSymbols: (syms: string[]) => void;
  setSnapshot: (s: MarketSnapshot) => void;
  updateKline: (symbol: string, tf: string, candle: Candle) => void;
  addSignal: (s: Signal) => void;
  removeSignal: (id: string) => void;
  setPosition: (p: Position) => void;
  removePosition: (symbol: string) => void;
  addTrade: (t: Trade) => void;
  setRegime: (symbol: string, regime: string) => void;
  setPendingOrder: (o: PendingOrder) => void;
  removePendingOrder: (symbol: string) => void;
  setMLStats: (s: MLStats) => void;
  setWsConnected: (c: boolean) => void;
  setSettingsOpen: (o: boolean) => void;
  setTradeHistoryOpen: (o: boolean) => void;
  setSizeMode: (m: 'FIXED' | 'ADAPTIVE' | 'PERCENT') => void;
  setFixedAmount: (a: number) => void;
  setAdaptiveBase: (a: number) => void;
  setPercentValue: (v: number) => void;
}

export const useTradingStore = create<TradingState>((set, get) => ({
  mode: 'paper',
  balance: 0,
  dailyPnl: 0,
  selectedSymbol: 'BTCUSDT',
  symbols: ['BTCUSDT', 'ETHUSDT'],
  regimes: {},
  snapshots: {},
  signals: [],
  positions: [],
  pendingOrders: [],
  trades: [],
  mlStats: { samples: 0, accuracy: 0, recent_accuracy: 0, drift: 'Stable' },
  wsConnected: false,
  settingsOpen: false,
  tradeHistoryOpen: false,
  sizeMode: 'FIXED',
  fixedAmount: 100,
  adaptiveBase: 100,
  percentValue: 5,

  winRate: () => {
    const t = get().trades;
    if (t.length === 0) return 0;
    return (t.filter((x) => x.pnl > 0).length / t.length) * 100;
  },
  profitFactor: () => {
    const t = get().trades;
    const wins = t.filter((x) => x.pnl > 0).reduce((s, x) => s + x.pnl, 0);
    const losses = Math.abs(
      t.filter((x) => x.pnl < 0).reduce((s, x) => s + x.pnl, 0),
    );
    return losses === 0 ? wins : wins / losses;
  },
  totalTrades: () => get().trades.length,

  setMode: (m) => set({ mode: m }),
  setBalance: (b, pnl) => set({ balance: b, dailyPnl: pnl }),
  setSelectedSymbol: (s) => set({ selectedSymbol: s }),
  setSymbols: (syms) => set({ symbols: syms }),
  setSnapshot: (s) =>
    set((st) => {
      const existing = st.snapshots[s.symbol];
      return {
        snapshots: {
          ...st.snapshots,
          [s.symbol]: {
            ...s,
            klines_1m: s.klines_1m?.length ? s.klines_1m : existing?.klines_1m ?? [],
            klines_3m: s.klines_3m?.length ? s.klines_3m : existing?.klines_3m ?? [],
            klines_5m: s.klines_5m?.length ? s.klines_5m : existing?.klines_5m ?? [],
          },
        },
      };
    }),
  updateKline: (symbol, tf, candle) =>
    set((st) => {
      const snap = st.snapshots[symbol];
      if (!snap) return st;
      const key = `klines_${tf}` as 'klines_1m' | 'klines_3m' | 'klines_5m';
      const klines = [...(snap[key] || [])];
      const last = klines[klines.length - 1];
      if (last && last.t === candle.t) {
        klines[klines.length - 1] = candle;
      } else {
        klines.push(candle);
        if (klines.length > 500) klines.shift();
      }
      return {
        snapshots: {
          ...st.snapshots,
          [symbol]: { ...snap, [key]: klines },
        },
      };
    }),
  addSignal: (s) => set((st) => ({ signals: [...st.signals, s] })),
  removeSignal: (id) =>
    set((st) => ({ signals: st.signals.filter((x) => x.id !== id) })),
  setPosition: (p) =>
    set((st) => ({
      positions: [
        ...st.positions.filter((x) => x.symbol !== p.symbol),
        p,
      ],
    })),
  removePosition: (symbol) =>
    set((st) => ({
      positions: st.positions.filter((x) => x.symbol !== symbol),
    })),
  addTrade: (t) => set((st) => ({ trades: [...st.trades, t] })),
  setRegime: (symbol, regime) =>
    set((st) => ({ regimes: { ...st.regimes, [symbol]: regime } })),
  setPendingOrder: (o) =>
    set((st) => ({
      pendingOrders: [
        ...st.pendingOrders.filter((x) => x.symbol !== o.symbol),
        o,
      ],
    })),
  removePendingOrder: (symbol) =>
    set((st) => ({
      pendingOrders: st.pendingOrders.filter((x) => x.symbol !== symbol),
    })),
  setMLStats: (s) => set({ mlStats: s }),
  setWsConnected: (c) => set({ wsConnected: c }),
  setSettingsOpen: (o) => set({ settingsOpen: o }),
  setTradeHistoryOpen: (o) => set({ tradeHistoryOpen: o }),
  setSizeMode: (m) => set({ sizeMode: m }),
  setFixedAmount: (a) => set({ fixedAmount: a }),
  setAdaptiveBase: (a) => set({ adaptiveBase: a }),
  setPercentValue: (v) => set({ percentValue: v }),
}));
