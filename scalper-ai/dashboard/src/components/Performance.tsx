import React, { useState } from 'react';
import { useTradingStore } from '../store/tradingStore';

type Tab = 'session' | 'total';

export const Performance: React.FC = () => {
  const [tab, setTab] = useState<Tab>('session');
  const dailyPnl = useTradingStore((s) => s.dailyPnl);
  const winRate = useTradingStore((s) => s.winRate);
  const totalTrades = useTradingStore((s) => s.totalTrades);
  const positions = useTradingStore((s) => s.positions);

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
          <span style={{ color: dailyPnl >= 0 ? 'var(--green)' : 'var(--red)' }}>
            {dailyPnl >= 0 ? '+' : ''}${dailyPnl.toFixed(2)}
          </span>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <span style={{ color: 'var(--text-secondary)' }}>Win Rate</span>
          <span>{winRate().toFixed(1)}%</span>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <span style={{ color: 'var(--text-secondary)' }}>Trades</span>
          <span>{totalTrades()}</span>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <span style={{ color: 'var(--text-secondary)' }}>Positions</span>
          <span>{positions.length}</span>
        </div>
      </div>
    </div>
  );
};
