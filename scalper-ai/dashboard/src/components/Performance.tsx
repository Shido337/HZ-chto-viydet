import React, { useEffect, useState } from 'react';
import { useTradingStore } from '../store/tradingStore';

type Tab = 'session' | 'total';

interface TotalStats {
  total_trades: number;
  total_pnl: number;
  win_rate: number;
}

export const Performance: React.FC = () => {
  const [tab, setTab] = useState<Tab>('session');
  const [totalStats, setTotalStats] = useState<TotalStats | null>(null);
  const dailyPnl = useTradingStore((s) => s.dailyPnl);
  const winRate = useTradingStore((s) => s.winRate);
  const totalTrades = useTradingStore((s) => s.totalTrades);
  const positions = useTradingStore((s) => s.positions);

  useEffect(() => {
    if (tab === 'total') {
      fetch('/api/trades/summary')
        .then((r) => r.json())
        .then(setTotalStats)
        .catch(() => {});
    }
  }, [tab]);

  const pnl = tab === 'total' && totalStats ? totalStats.total_pnl : dailyPnl;
  const wr = tab === 'total' && totalStats ? totalStats.win_rate : winRate();
  const trades = tab === 'total' && totalStats ? totalStats.total_trades : totalTrades();

  return (
    <div className="panel-section">
      <div className="panel-header">Performance</div>
      <div className="tabs">
        <button
          className={`tab-btn ${tab === 'session' ? 'active' : ''}`}
          onClick={() => setTab('session')}
        >
          Session
        </button>
        <button
          className={`tab-btn ${tab === 'total' ? 'active' : ''}`}
          onClick={() => setTab('total')}
        >
          Total
        </button>
      </div>
      <div style={{ fontSize: 12 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <span style={{ color: 'var(--text-secondary)' }}>P&L</span>
          <span style={{ color: pnl >= 0 ? 'var(--green)' : 'var(--red)' }}>
            {pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}
          </span>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <span style={{ color: 'var(--text-secondary)' }}>Win Rate</span>
          <span>{wr.toFixed(1)}%</span>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <span style={{ color: 'var(--text-secondary)' }}>Trades</span>
          <span>{trades}</span>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <span style={{ color: 'var(--text-secondary)' }}>Positions</span>
          <span>{positions.length}</span>
        </div>
      </div>
    </div>
  );
};
