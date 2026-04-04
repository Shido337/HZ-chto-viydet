import React from 'react';
import { useTradingStore } from '../store/tradingStore';

export const MLModel: React.FC = () => {
  const ml = useTradingStore((s) => s.mlStats);

  return (
    <div className="panel-section">
      <div className="panel-header">ML Model</div>
      <div style={{ fontSize: 11 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <span style={{ color: 'var(--text-secondary)' }}>Samples</span>
          <span>{ml.samples}</span>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <span style={{ color: 'var(--text-secondary)' }}>Accuracy</span>
          <span>{ml.accuracy.toFixed(1)}%</span>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <span style={{ color: 'var(--text-secondary)' }}>Recent</span>
          <span>{ml.recent_accuracy.toFixed(1)}%</span>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <span style={{ color: 'var(--text-secondary)' }}>Drift</span>
          <span
            style={{
              color: ml.drift === 'Stable' ? 'var(--green)' : 'var(--orange)',
            }}
          >
            {ml.drift}
          </span>
        </div>
      </div>
    </div>
  );
};
