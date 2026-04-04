import React, { useState } from 'react';
import { useTradingStore } from '../store/tradingStore';

const FIXED_DEFAULTS = [10, 50, 100, 200, 500];
const PERCENT_DEFAULTS = [1, 2, 5, 10, 20];
const LEVERAGE = 25;

const SCORE_MULTIPLIERS = [
  { range: '0.65–0.72', mult: '0.75×' },
  { range: '0.73–0.80', mult: '1.00×' },
  { range: '0.81–0.90', mult: '1.25×' },
  { range: '0.91–1.00', mult: '1.50×' },
];

export const SizeSettings: React.FC = () => {
  const sizeMode = useTradingStore((s) => s.sizeMode);
  const setSizeMode = useTradingStore((s) => s.setSizeMode);
  const fixedAmount = useTradingStore((s) => s.fixedAmount);
  const setFixedAmount = useTradingStore((s) => s.setFixedAmount);
  const adaptiveBase = useTradingStore((s) => s.adaptiveBase);
  const setAdaptiveBase = useTradingStore((s) => s.setAdaptiveBase);
  const percentValue = useTradingStore((s) => s.percentValue);
  const setPercentValue = useTradingStore((s) => s.setPercentValue);
  const balance = useTradingStore((s) => s.balance);

  const [fixedButtons, setFixedButtons] = useState(FIXED_DEFAULTS);
  const [percentButtons, setPercentButtons] = useState(PERCENT_DEFAULTS);

  const effectiveSize = (() => {
    if (sizeMode === 'FIXED') return fixedAmount;
    if (sizeMode === 'ADAPTIVE') return adaptiveBase;
    return balance * (percentValue / 100);
  })();

  return (
    <div>
      <div className="tabs" style={{ marginBottom: 8 }}>
        {(['FIXED', 'ADAPTIVE', 'PERCENT'] as const).map((m) => (
          <button
            key={m}
            className={`tab-btn ${sizeMode === m ? 'active' : ''}`}
            onClick={() => setSizeMode(m)}
          >
            {m}
          </button>
        ))}
      </div>

      {sizeMode === 'FIXED' && (
        <div className="size-buttons-row">
          {fixedButtons.map((v, i) => (
            <input
              key={i}
              type="number"
              className={`size-edit-btn ${fixedAmount === v ? 'selected' : ''}`}
              value={v}
              onChange={(e) => {
                const nv = Number(e.target.value);
                const updated = [...fixedButtons];
                updated[i] = nv;
                setFixedButtons(updated);
              }}
              onClick={() => setFixedAmount(v)}
            />
          ))}
        </div>
      )}

      {sizeMode === 'ADAPTIVE' && (
        <>
          <div className="size-buttons-row">
            {fixedButtons.map((v, i) => (
              <input
                key={i}
                type="number"
                className={`size-edit-btn ${adaptiveBase === v ? 'selected' : ''}`}
                value={v}
                onChange={(e) => {
                  const nv = Number(e.target.value);
                  const updated = [...fixedButtons];
                  updated[i] = nv;
                  setFixedButtons(updated);
                }}
                onClick={() => setAdaptiveBase(v)}
              />
            ))}
          </div>
          <table className="mult-table">
            <thead>
              <tr>
                <th>Score</th>
                <th>Multiplier</th>
              </tr>
            </thead>
            <tbody>
              {SCORE_MULTIPLIERS.map((r) => (
                <tr key={r.range}>
                  <td>{r.range}</td>
                  <td>{r.mult}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      {sizeMode === 'PERCENT' && (
        <div className="size-buttons-row">
          {percentButtons.map((v, i) => (
            <input
              key={i}
              type="number"
              className={`size-edit-btn ${percentValue === v ? 'selected' : ''}`}
              value={v}
              onChange={(e) => {
                const nv = Number(e.target.value);
                const updated = [...percentButtons];
                updated[i] = nv;
                setPercentButtons(updated);
              }}
              onClick={() => setPercentValue(v)}
            />
          ))}
        </div>
      )}

      <div className="effective-size">
        Effective: ${effectiveSize.toFixed(2)} notional (${(effectiveSize * LEVERAGE).toFixed(2)} @ {LEVERAGE}x)
      </div>
    </div>
  );
};
