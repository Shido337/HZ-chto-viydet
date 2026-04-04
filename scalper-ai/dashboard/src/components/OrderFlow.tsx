import React from 'react';
import { useTradingStore } from '../store/tradingStore';

export const OrderFlow: React.FC = () => {
  const symbol = useTradingStore((s) => s.selectedSymbol);
  const snap = useTradingStore((s) => s.snapshots[symbol]);

  const bidQty = snap?.bid_qty ?? 0;
  const askQty = snap?.ask_qty ?? 0;
  const total = bidQty + askQty;
  const bidPct = total > 0 ? (bidQty / total) * 100 : 50;
  const askPct = 100 - bidPct;

  return (
    <div className="panel-section">
      <div className="panel-header">Order Flow</div>
      <div className="ob-bar">
        <div className="ob-bid" style={{ width: `${bidPct}%` }} />
        <div className="ob-ask" style={{ width: `${askPct}%` }} />
      </div>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          fontSize: 10,
          marginTop: 2,
        }}
      >
        <span style={{ color: 'var(--cyan)' }}>BID {bidPct.toFixed(0)}%</span>
        <span style={{ color: 'var(--orange)' }}>ASK {askPct.toFixed(0)}%</span>
      </div>
    </div>
  );
};
