import React from 'react';
import { useTradingStore } from '../store/tradingStore';

export const CoinWatch: React.FC = () => {
  const symbols = useTradingStore((s) => s.symbols);
  const selected = useTradingStore((s) => s.selectedSymbol);
  const snapshots = useTradingStore((s) => s.snapshots);
  const regime = useTradingStore((s) => s.regimes[selected] ?? 'NORMAL');
  const setSelected = useTradingStore((s) => s.setSelectedSymbol);

  return (
    <div className="panel-section">
      <div className="panel-header">
        Coin Watch <span className="badge badge-regime">{regime}</span>
      </div>
      {symbols.map((sym) => {
        const snap = snapshots[sym];
        const change = snap
          ? ((snap.price - (snap.klines_1m?.[0]?.o ?? snap.price)) /
              (snap.klines_1m?.[0]?.o || 1)) *
            100
          : 0;
        const isUp = change >= 0;
        return (
          <div
            key={sym}
            className={`coin-item ${sym === selected ? 'selected' : ''}`}
            onClick={() => setSelected(sym)}
          >
            <span>{sym.replace('USDT', '')}</span>
            <span style={{ color: isUp ? 'var(--green)' : 'var(--red)' }}>
              {isUp ? '+' : ''}
              {change.toFixed(2)}%
            </span>
          </div>
        );
      })}
    </div>
  );
};
