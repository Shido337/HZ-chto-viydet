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
}

export interface Trade {
  symbol: string;
  direction: 'LONG' | 'SHORT';
  pnl: number;
  reason: string;
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

export type WsEvent =
  | { type: 'market_snapshot'; data: MarketSnapshot }
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
