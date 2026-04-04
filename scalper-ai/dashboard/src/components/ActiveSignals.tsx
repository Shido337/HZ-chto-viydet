import React from 'react';
import { useTradingStore } from '../store/tradingStore';

export const ActiveSignals: React.FC = () => {
  const signals = useTradingStore((s) => s.signals);

  return (
    <div className="panel-section">
      <div className="panel-header">Active Signals</div>
      {signals.length === 0 && (
        <div style={{ fontSize: 11, color: 'var(--text-secondary)' }}>
          No active signals
        </div>
      )}
      {signals.map((sig) => (
        <div key={sig.id} className="signal-card">
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
            <span
              className={`badge ${
                sig.direction === 'LONG' ? 'badge-long' : 'badge-short'
              }`}
            >
              {sig.direction}
            </span>
            <span style={{ color: 'var(--cyan)', fontWeight: 600 }}>
              {(sig.score * 5).toFixed(1)}
            </span>
          </div>
          <div style={{ color: 'var(--text-secondary)', fontSize: 10 }}>
            {sig.setup_type.replace(/_/g, ' ')}
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10 }}>
            <span>{sig.symbol}</span>
            <span>E: {sig.entry_price.toFixed(2)}</span>
          </div>
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              fontSize: 10,
              color: 'var(--text-secondary)',
            }}
          >
            <span>SL: {sig.sl_price.toFixed(2)}</span>
            <span>TP: {sig.tp_price.toFixed(2)}</span>
          </div>
        </div>
      ))}
    </div>
  );
};
