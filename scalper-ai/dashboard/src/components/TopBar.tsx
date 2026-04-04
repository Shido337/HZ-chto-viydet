import React from 'react';
import { useTradingStore } from '../store/tradingStore';

const SIZE_OPTIONS = [10, 50, 100, 200, 500];

export const TopBar: React.FC = () => {
  const mode = useTradingStore((s) => s.mode);
  const balance = useTradingStore((s) => s.balance);
  const dailyPnl = useTradingStore((s) => s.dailyPnl);
  const wsConnected = useTradingStore((s) => s.wsConnected);
  const fixedAmount = useTradingStore((s) => s.fixedAmount);
  const winRate = useTradingStore((s) => s.winRate);
  const totalTrades = useTradingStore((s) => s.totalTrades);
  const selectedSymbol = useTradingStore((s) => s.selectedSymbol);
  const regime = useTradingStore((s) => s.regimes[selectedSymbol] ?? 'RANGING');

  const setMode = useTradingStore((s) => s.setMode);
  const setFixedAmount = useTradingStore((s) => s.setFixedAmount);
  const setSettingsOpen = useTradingStore((s) => s.setSettingsOpen);

  const switchMode = async (m: 'paper' | 'live') => {
    const res = await fetch(`/api/mode/${m}`, { method: 'POST' });
    const data = await res.json();
    if (!data.error) setMode(m);
  };

  const handleSizeChange = (v: number) => {
    setFixedAmount(v);
    fetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ fixed_amount: v }),
    }).catch(() => {});
  };

  const handleStop = async () => {
    await fetch('/api/stop', { method: 'POST' });
  };

  const pnlClass = dailyPnl >= 0 ? 'positive' : 'negative';

  return (
    <div className="top-bar">
      <button
        className={`mode-btn ${mode === 'paper' ? 'active-paper' : ''}`}
        onClick={() => switchMode('paper')}
      >
        PAPER
      </button>
      <button
        className={`mode-btn ${mode === 'live' ? 'active-live' : ''}`}
        onClick={() => switchMode('live')}
      >
        LIVE
      </button>

      <span style={{ fontSize: 11, color: 'var(--text-secondary)' }}>
        LIVE DATA <span className={`status-dot ${wsConnected ? 'green' : 'red'}`} />
      </span>
      <span style={{ fontSize: 11, color: 'var(--text-secondary)' }}>
        WS <span className={`status-dot ${wsConnected ? 'green' : 'red'}`} />
      </span>
      <span className="badge badge-regime">{regime}</span>

      <div style={{ display: 'flex', gap: 4, marginLeft: 8 }}>
        {SIZE_OPTIONS.map((v) => (
          <button
            key={v}
            className={`size-btn ${fixedAmount === v ? 'selected' : ''}`}
            onClick={() => handleSizeChange(v)}
          >
            ${v}
          </button>
        ))}
      </div>

      <div className="spacer" />

      <div className="stat-item">
        <span className="stat-label">Daily P&L</span>
        <span className={`stat-value ${pnlClass}`}>
          {dailyPnl >= 0 ? '+' : ''}${dailyPnl.toFixed(2)}
        </span>
      </div>
      <div className="stat-item">
        <span className="stat-label">Portfolio</span>
        <span className="stat-value">${balance.toFixed(2)}</span>
      </div>
      <div className="stat-item">
        <span className="stat-label">WR</span>
        <span className="stat-value">{winRate().toFixed(1)}%</span>
      </div>
      <div className="stat-item">
        <span className="stat-label">Trades</span>
        <span className="stat-value">{totalTrades()}</span>
      </div>

      <button className="btn-settings" onClick={() => setSettingsOpen(true)}>
        ⚙
      </button>
      <button className="btn-stop" onClick={handleStop}>
        STOP
      </button>
    </div>
  );
};
