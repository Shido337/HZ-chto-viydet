import React from 'react';
import { useTradingStore } from '../store/tradingStore';

export const PendingLimitsTable: React.FC = () => {
  const orders = useTradingStore((s) => s.pendingOrders);
  const snapshots = useTradingStore((s) => s.snapshots);
  const setSelectedSymbol = useTradingStore((s) => s.setSelectedSymbol);

  const handleCancel = async (_symbol: string) => {
    await fetch(`/api/stop`, { method: 'POST' });
  };

  return (
    <div className="positions-table">
      <table>
        <thead>
          <tr>
            <th>Symbol</th>
            <th>Size $</th>
            <th>Setup</th>
            <th>Limit</th>
            <th>Current</th>
            <th>Fill%</th>
            <th>Notional</th>
            <th>Expiry</th>
            <th>Action</th>
          </tr>
        </thead>
        <tbody>
          {orders.length === 0 && (
            <tr>
              <td colSpan={9} style={{ textAlign: 'center', color: 'var(--text-secondary)' }}>
                No pending orders
              </td>
            </tr>
          )}
          {orders.map((o) => {
            const snap = snapshots[o.symbol];
            const currentPrice = snap?.price ?? 0;
            const fillPct =
              o.price > 0
                ? Math.min(
                    100,
                    (1 - Math.abs(currentPrice - o.price) / o.price) * 100,
                  )
                : 0;
            const expiryStr = o.expiry
              ? new Date(o.expiry).toLocaleTimeString()
              : '—';
            return (
              <tr key={o.symbol} onClick={() => setSelectedSymbol(o.symbol)} style={{ cursor: 'pointer' }}>
                <td>{o.symbol.replace('USDT', '')}</td>
                <td>{o.size_usdt.toFixed(2)}</td>
                <td style={{ fontSize: 10 }}>{o.setup_type.replace(/_/g, ' ')}</td>
                <td>{o.price.toFixed(2)}</td>
                <td>{currentPrice ? currentPrice.toFixed(2) : '—'}</td>
                <td>{fillPct.toFixed(0)}%</td>
                <td>{o.notional.toFixed(2)}</td>
                <td>{expiryStr}</td>
                <td>
                  <button
                    className="btn-close-pos"
                    onClick={() => handleCancel(o.symbol)}
                  >
                    Cancel
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
};
