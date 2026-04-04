import React from 'react';
import { useTradingStore } from '../store/tradingStore';

export const Monitor: React.FC = () => {
  const balance = useTradingStore((s) => s.balance);
  const dailyPnl = useTradingStore((s) => s.dailyPnl);
  const positions = useTradingStore((s) => s.positions);
  const pending = useTradingStore((s) => s.pendingOrders);
  const signals = useTradingStore((s) => s.signals);
  const trades = useTradingStore((s) => s.trades);
  const winRate = useTradingStore((s) => s.winRate);

  const openPnl = positions.reduce((s, p) => s + p.current_pnl, 0);
  const wins = trades.filter((t) => t.pnl > 0);
  const losses = trades.filter((t) => t.pnl < 0);
  const maxWin = wins.length > 0 ? Math.max(...wins.map((t) => t.pnl)) : 0;
  const maxLoss = losses.length > 0 ? Math.min(...losses.map((t) => t.pnl)) : 0;
  const avgWin = wins.length > 0 ? wins.reduce((s, t) => s + t.pnl, 0) / wins.length : 0;
  const avgLoss =
    losses.length > 0 ? losses.reduce((s, t) => s + t.pnl, 0) / losses.length : 0;

  const rows: [string, string][] = [
    ['Portfolio', `$${balance.toFixed(2)}`],
    ['Daily P&L', `${dailyPnl >= 0 ? '+' : ''}$${dailyPnl.toFixed(2)}`],
    ['Open P&L', `${openPnl >= 0 ? '+' : ''}$${openPnl.toFixed(2)}`],
    ['Open', `${positions.length}`],
    ['Pending', `${pending.length}`],
    ['Signals', `${signals.length}`],
    ['Traded', `${trades.length}`],
    ['Win Rate', `${winRate().toFixed(1)}%`],
    ['Max Win', `$${maxWin.toFixed(2)}`],
    ['Max Loss', `$${maxLoss.toFixed(2)}`],
    ['Avg Win', `$${avgWin.toFixed(2)}`],
    ['Avg Loss', `$${avgLoss.toFixed(2)}`],
    ['Loss Hit', `${losses.length}`],
  ];

  return (
    <div className="panel-section">
      <div className="panel-header">Monitor (5 min)</div>
      <div className="monitor-grid">
        {rows.map(([label, value]) => (
          <React.Fragment key={label}>
            <span className="monitor-label">{label}</span>
            <span className="monitor-value">{value}</span>
          </React.Fragment>
        ))}
      </div>
    </div>
  );
};
