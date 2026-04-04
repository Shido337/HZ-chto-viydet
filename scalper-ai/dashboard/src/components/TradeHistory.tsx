import React, { useEffect, useState } from 'react';
import type { TradeHistoryRecord } from '../types';

interface Props {
  open: boolean;
  onClose: () => void;
}

export const TradeHistory: React.FC<Props> = ({ open, onClose }) => {
  const [trades, setTrades] = useState<TradeHistoryRecord[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    fetch('/api/trades?limit=500')
      .then((r) => r.json())
      .then((data) => setTrades(data))
      .catch(() => setTrades([]))
      .finally(() => setLoading(false));
  }, [open]);

  if (!open) return null;

  const totalPnl = trades.reduce((s, t) => s + (t.pnl ?? 0), 0);
  const wins = trades.filter((t) => t.pnl > 0).length;
  const losses = trades.filter((t) => t.pnl < 0).length;
  const winRate = trades.length > 0 ? (wins / trades.length) * 100 : 0;
  const avgWin =
    wins > 0
      ? trades.filter((t) => t.pnl > 0).reduce((s, t) => s + t.pnl, 0) / wins
      : 0;
  const avgLoss =
    losses > 0
      ? trades.filter((t) => t.pnl < 0).reduce((s, t) => s + t.pnl, 0) / losses
      : 0;

  const fmtTime = (iso: string | null) => {
    if (!iso) return '—';
    const d = new Date(iso);
    return d.toLocaleString(undefined, {
      month: 'short',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="modal-content trade-history-modal"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-header">
          Trade History
          <button
            className="modal-close-btn"
            onClick={onClose}
          >
            ✕
          </button>
        </div>

        <div className="th-summary">
          <div className="th-stat">
            <span className="th-stat-label">Total</span>
            <span className="th-stat-value">{trades.length}</span>
          </div>
          <div className="th-stat">
            <span className="th-stat-label">Wins</span>
            <span className="th-stat-value" style={{ color: 'var(--green)' }}>
              {wins}
            </span>
          </div>
          <div className="th-stat">
            <span className="th-stat-label">Losses</span>
            <span className="th-stat-value" style={{ color: 'var(--red)' }}>
              {losses}
            </span>
          </div>
          <div className="th-stat">
            <span className="th-stat-label">Win Rate</span>
            <span className="th-stat-value">{winRate.toFixed(1)}%</span>
          </div>
          <div className="th-stat">
            <span className="th-stat-label">Avg Win</span>
            <span className="th-stat-value" style={{ color: 'var(--green)' }}>
              +${avgWin.toFixed(4)}
            </span>
          </div>
          <div className="th-stat">
            <span className="th-stat-label">Avg Loss</span>
            <span className="th-stat-value" style={{ color: 'var(--red)' }}>
              ${avgLoss.toFixed(4)}
            </span>
          </div>
          <div className="th-stat">
            <span className="th-stat-label">Total P&L</span>
            <span
              className="th-stat-value"
              style={{ color: totalPnl >= 0 ? 'var(--green)' : 'var(--red)' }}
            >
              {totalPnl >= 0 ? '+' : ''}${totalPnl.toFixed(4)}
            </span>
          </div>
        </div>

        {loading ? (
          <div style={{ textAlign: 'center', padding: 20, color: 'var(--text-secondary)' }}>
            Loading...
          </div>
        ) : (
          <div className="th-table-wrap">
            <table>
              <thead>
                <tr>
                  <th>#</th>
                  <th>Symbol</th>
                  <th>Dir</th>
                  <th>Setup</th>
                  <th>Score</th>
                  <th>Entry</th>
                  <th>Exit</th>
                  <th>SL</th>
                  <th>TP</th>
                  <th>Size $</th>
                  <th>P&L</th>
                  <th>Result</th>
                  <th>Reason</th>
                  <th>Opened</th>
                  <th>Closed</th>
                </tr>
              </thead>
              <tbody>
                {trades.length === 0 && (
                  <tr>
                    <td
                      colSpan={15}
                      style={{ textAlign: 'center', color: 'var(--text-secondary)', padding: 20 }}
                    >
                      No trades yet
                    </td>
                  </tr>
                )}
                {trades.map((t) => {
                  const pnlColor = t.pnl >= 0 ? 'var(--green)' : 'var(--red)';
                  const resultBadge =
                    t.result === 'WIN'
                      ? 'badge-long'
                      : t.result === 'LOSS'
                        ? 'badge-short'
                        : 'badge-regime';
                  return (
                    <tr key={t.id}>
                      <td>{t.id}</td>
                      <td>{t.symbol.replace('USDT', '')}</td>
                      <td>
                        <span
                          className={`badge ${t.direction === 'LONG' ? 'badge-long' : 'badge-short'}`}
                        >
                          {t.direction}
                        </span>
                      </td>
                      <td style={{ fontSize: 10 }}>
                        {t.setup_type.replace(/_/g, ' ')}
                      </td>
                      <td>{(t.score * 5).toFixed(1)}</td>
                      <td>{t.entry_price?.toFixed(6)}</td>
                      <td>{t.exit_price?.toFixed(6)}</td>
                      <td style={{ color: 'var(--red)' }}>{t.sl_price?.toFixed(6)}</td>
                      <td style={{ color: 'var(--green)' }}>{t.tp_price?.toFixed(6)}</td>
                      <td>{t.size_usdt?.toFixed(2)}</td>
                      <td style={{ color: pnlColor, fontWeight: 600 }}>
                        {t.pnl >= 0 ? '+' : ''}
                        {t.pnl?.toFixed(4)}
                      </td>
                      <td>
                        <span className={`badge ${resultBadge}`}>{t.result}</span>
                      </td>
                      <td style={{ fontSize: 10 }}>{t.exit_reason}</td>
                      <td style={{ fontSize: 10 }}>{fmtTime(t.opened_at)}</td>
                      <td style={{ fontSize: 10 }}>{fmtTime(t.closed_at)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
};
