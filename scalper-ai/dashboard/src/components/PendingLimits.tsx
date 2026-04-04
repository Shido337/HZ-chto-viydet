import React from 'react';
import { useTradingStore } from '../store/tradingStore';

export const PendingLimits: React.FC = () => {
  const orders = useTradingStore((s) => s.pendingOrders);

  return (
    <div className="panel-section">
      <div className="panel-header">Pending</div>
      {orders.length === 0 && (
        <div style={{ fontSize: 11, color: 'var(--text-secondary)' }}>
          No pending orders
        </div>
      )}
      {orders.map((o) => (
        <div
          key={o.symbol}
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            fontSize: 11,
            padding: '2px 0',
          }}
        >
          <span>
            <span
              className={`badge ${
                o.direction === 'LONG' ? 'badge-long' : 'badge-short'
              }`}
            >
              {o.direction}
            </span>{' '}
            {o.symbol.replace('USDT', '')}
          </span>
          <span>${o.price.toFixed(2)}</span>
        </div>
      ))}
    </div>
  );
};
