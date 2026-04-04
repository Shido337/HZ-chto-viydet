import React, { useState } from 'react';
import { AreaChart, Area, ResponsiveContainer, YAxis } from 'recharts';
import { useTradingStore } from '../store/tradingStore';

type Period = '1H' | '4H' | '1D' | '1W';

export const EquityCurve: React.FC = () => {
  const [period, setPeriod] = useState<Period>('1D');
  const trades = useTradingStore((s) => s.trades);
  const balance = useTradingStore((s) => s.balance);

  // Build cumulative equity from trades
  let cum = balance;
  const data = trades.map((t, i) => {
    cum += t.pnl;
    return { idx: i, value: cum };
  });
  if (data.length === 0) {
    data.push({ idx: 0, value: balance });
  }

  const isUp = data[data.length - 1].value >= (data[0]?.value ?? 0);

  return (
    <div className="panel-section">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span className="panel-header" style={{ marginBottom: 0 }}>
          Equity Curve
        </span>
        <span style={{ fontSize: 12, fontWeight: 600 }}>${balance.toFixed(2)}</span>
      </div>
      <div className="tabs" style={{ marginTop: 4 }}>
        {(['1H', '4H', '1D', '1W'] as Period[]).map((p) => (
          <button
            key={p}
            className={`tab-btn ${period === p ? 'active' : ''}`}
            onClick={() => setPeriod(p)}
          >
            {p}
          </button>
        ))}
      </div>
      <div className="equity-container">
        <ResponsiveContainer width="100%" height={80}>
          <AreaChart data={data}>
            <YAxis domain={['auto', 'auto']} hide />
            <Area
              type="monotone"
              dataKey="value"
              stroke={isUp ? 'var(--green)' : 'var(--red)'}
              fill={isUp ? 'rgba(0,212,170,0.15)' : 'rgba(255,68,102,0.15)'}
              strokeWidth={1.5}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
};
