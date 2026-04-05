import React from 'react';
import { useTradingStore } from '../store/tradingStore';
import { fmtPrice, fmtScore } from '../types';

export const ActiveSignals: React.FC = () => {
  const signals = useTradingStore((s) => s.signals);

  const recent = signals.slice(-5);

  return (
    <div className="panel-section" style={{ maxHeight: 220, overflow: 'auto' }}>
      <div className="panel-header">
        Active Signals{' '}
        <span style={{ color: 'var(--cyan)', fontWeight: 400 }}>({signals.length})</span>
      </div>
      {signals.length === 0 && (
        <div style={{ fontSize: 11, color: 'var(--text-secondary)' }}>
          No active signals
        </div>
      )}
      {recent.map((sig) => (
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
              {fmtScore(sig.score)}
            </span>
          </div>
          <div style={{ color: 'var(--text-secondary)', fontSize: 10 }}>
            {sig.setup_type.replace(/_/g, ' ')}
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10 }}>
            <span>{sig.symbol}</span>
            <span>E: {fmtPrice(sig.entry_price)}</span>
          </div>
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              fontSize: 10,
              color: 'var(--text-secondary)',
            }}
          >
            <span>SL: {fmtPrice(sig.sl_price)}</span>
            <span>TP: {fmtPrice(sig.tp_price)}</span>
          </div>
        </div>
      ))}
    </div>
  );
};
