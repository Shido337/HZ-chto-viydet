/* -----------------------------------------------------------------------
   Types — SCALPER-AI Dashboard
   ----------------------------------------------------------------------- */

export interface MarketSnapshot {
  symbol: string;
  price: number;
  bid: number;
  ask: number;
  bid_qty: number;
  ask_qty: number;
  cvd: number;
  cvd_delta_1m: number;
  volume_1m: number;
  regime: string;
  indicators: IndicatorSet;
  klines_1m: Candle[];
  klines_3m: Candle[];
  klines_5m: Candle[];
}

export interface IndicatorSet {
  adx: number;
  atr: number;
  ema9: number;
  ema21: number;
  vwap: number;
  rsi: number;
  atr_percentile: number;
}

export interface Candle {
  t: number;
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
  T: number;
  closed: boolean;
}

export interface Signal {
  id: string;
  symbol: string;
  direction: 'LONG' | 'SHORT';
  setup_type: string;
  score: number;
  entry_price: number;
  sl_price: number;
  tp_price: number;
  created_at: number;
}

export interface Position {
  id: string;
  symbol: string;
  direction: 'LONG' | 'SHORT';
  setup_type: string;
  score: number;
  entry_price: number;
  sl_price: number;
  tp_price: number;
  size_usdt: number;
  current_pnl: number;
  liquidation_price: number;
  trailing_activated: boolean;
  breakeven_moved: boolean;
  best_price: number;
}

export interface Trade {
  symbol: string;
  direction: 'LONG' | 'SHORT';
  pnl: number;
  reason: string;
}

export interface TradeHistoryRecord {
  id: number;
  symbol: string;
  direction: string;
  setup_type: string;
  score: number;
  entry_price: number;
  exit_price: number;
  sl_price: number;
  tp_price: number;
  size_usdt: number;
  pnl: number;
  result: string;
  exit_reason: string;
  opened_at: string | null;
  closed_at: string | null;
}

export interface PendingOrder {
  symbol: string;
  direction: 'LONG' | 'SHORT';
  setup_type: string;
  price: number;
  size_usdt: number;
  notional: number;
  expiry: number;
}

export interface MLStats {
  samples: number;
  accuracy: number;
  recent_accuracy: number;
  drift: string;
}

export interface InitState {
  symbols: string[];
  balance: number;
  daily_pnl: number;
  mode: 'paper' | 'live';
  regimes: Record<string, string>;
}

/** Adaptive price formatter: more decimals for small-priced tokens */
export function fmtPrice(p: number): string {
  if (!p || p === 0) return '0.00';
  const a = Math.abs(p);
  if (a >= 1000) return p.toFixed(2);
  if (a >= 10)   return p.toFixed(3);
  if (a >= 1)    return p.toFixed(4);
  if (a >= 0.1)  return p.toFixed(5);
  return p.toFixed(6);
}

/** Score as percentage string, e.g. "73%" */
export function fmtScore(score: number): string {
  return `${(score * 100).toFixed(0)}%`;
}

export type WsEvent =
  | { type: 'init_state'; data: InitState }
  | { type: 'market_snapshot'; data: MarketSnapshot }
  | { type: 'kline_update'; data: { symbol: string; tf: string; candle: Candle } }
  | { type: 'signal_new'; data: Signal }
  | { type: 'signal_expired'; data: { id: string } }
  | { type: 'position_opened'; data: Position }
  | { type: 'position_updated'; data: Position }
  | { type: 'trade_closed'; data: Trade }
  | { type: 'pending_order_placed'; data: PendingOrder }
  | { type: 'pending_order_cancelled'; data: { symbol: string } }
  | { type: 'balance_update'; data: { balance: number; daily_pnl: number } }
  | { type: 'regime_update'; data: { symbol: string; regime: string } }
  | { type: 'error'; data: { message: string } };
