import React from 'react';
import { useTradingStore } from '../store/tradingStore';
import { fmtPrice, fmtScore } from '../types';

export const OpenPositions: React.FC = () => {
  const positions = useTradingStore((s) => s.positions);
  const snapshots = useTradingStore((s) => s.snapshots);
  const setSelectedSymbol = useTradingStore((s) => s.setSelectedSymbol);

  const handleClose = async (_symbol: string) => {
    await fetch('/api/stop', { method: 'POST' });
  };

  return (
    <div className="positions-table">
      <table>
        <thead>
          <tr>
            <th>Symbol</th>
            <th>Dir</th>
            <th>Setup</th>
            <th>Score</th>
            <th>Entry</th>
            <th>SL</th>
            <th>TP</th>
            <th>Size $</th>
            <th>Current</th>
            <th>P&amp;L</th>
            <th>Liq</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {positions.length === 0 && (
            <tr>
              <td colSpan={12} style={{ textAlign: 'center', color: 'var(--text-secondary)' }}>
                No open positions
              </td>
            </tr>
          )}
          {positions.map((p) => {
            const pnlColor = p.current_pnl >= 0 ? 'var(--green)' : 'var(--red)';
            const snap = snapshots[p.symbol];
            const currentPrice = snap?.price ?? 0;
            return (
              <tr key={p.id} onClick={() => setSelectedSymbol(p.symbol)} style={{ cursor: 'pointer' }}>
                <td>{p.symbol.replace('USDT', '')}</td>
                <td>
                  <span
                    className={`badge ${
                      p.direction === 'LONG' ? 'badge-long' : 'badge-short'
                    }`}
                  >
                    {p.direction}
                  </span>
                </td>
                <td style={{ fontSize: 10 }}>{p.setup_type.replace(/_/g, ' ')}</td>
                <td>{fmtScore(p.score)}</td>
                <td>{fmtPrice(p.entry_price)}</td>
                <td style={{ color: 'var(--red)' }}>{fmtPrice(p.sl_price)}</td>
                <td style={{ color: 'var(--green)' }}>{fmtPrice(p.tp_price)}</td>
                <td>{p.size_usdt.toFixed(2)}</td>
                <td>{currentPrice ? fmtPrice(currentPrice) : '—'}</td>
                <td style={{ color: pnlColor, fontWeight: 600 }}>
                  {p.current_pnl >= 0 ? '+' : ''}
                  {p.current_pnl.toFixed(2)}
                </td>
                <td style={{ color: 'var(--text-secondary)' }}>
                  {p.liquidation_price ? p.liquidation_price.toFixed(2) : '—'}
                </td>
                <td>
                  <button
                    className="btn-close-pos"
                    onClick={() => handleClose(p.symbol)}
                  >
                    ✕
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
