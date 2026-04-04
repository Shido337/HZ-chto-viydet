import React from 'react';
import { useTradingStore } from '../store/tradingStore';

const WR_TARGET = 50;
const PF_TARGET = 1.5;

export const Targets: React.FC = () => {
  const winRate = useTradingStore((s) => s.winRate);
  const profitFactor = useTradingStore((s) => s.profitFactor);

  const wr = winRate();
  const pf = profitFactor();

  return (
    <div className="panel-section">
      <div className="panel-header">Targets</div>
      <div style={{ fontSize: 11, marginBottom: 6 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <span>Win Rate</span>
          <span>{wr.toFixed(1)}% / {WR_TARGET}%</span>
        </div>
        <div className="progress-bar">
          <div
            className={`progress-fill ${wr >= WR_TARGET ? 'on-target' : 'below-target'}`}
            style={{ width: `${Math.min((wr / WR_TARGET) * 100, 100)}%` }}
          />
        </div>
      </div>
      <div style={{ fontSize: 11 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <span>Profit Factor</span>
          <span>{pf.toFixed(2)} / {PF_TARGET}</span>
        </div>
        <div className="progress-bar">
          <div
            className={`progress-fill ${pf >= PF_TARGET ? 'on-target' : 'below-target'}`}
            style={{ width: `${Math.min((pf / PF_TARGET) * 100, 100)}%` }}
          />
        </div>
      </div>
    </div>
  );
};
