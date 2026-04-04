import React, { useState } from 'react';
import { useTradingStore } from '../store/tradingStore';
import { SizeSettings } from './SizeSettings';

interface Props {
  open: boolean;
  onClose: () => void;
}

export const SettingsModal: React.FC<Props> = ({ open, onClose }) => {
  const mode = useTradingStore((s) => s.mode);
  const setMode = useTradingStore((s) => s.setMode);
  const symbols = useTradingStore((s) => s.symbols);
  const positions = useTradingStore((s) => s.positions);

  const [apiKey, setApiKey] = useState('');
  const [apiSecret, setApiSecret] = useState('');
  const [dailyLossLimit, setDailyLossLimit] = useState(15);
  const [maxPositions, setMaxPositions] = useState(5);
  const [enableCont, setEnableCont] = useState(true);
  const [enableMR, setEnableMR] = useState(true);
  const [enableEM, setEnableEM] = useState(true);
  const [telegramToken, setTelegramToken] = useState('');
  const [telegramChatId, setTelegramChatId] = useState('');
  const [showLiveConfirm, setShowLiveConfirm] = useState(false);

  if (!open) return null;

  const handleModeSwitch = async (m: 'paper' | 'live') => {
    if (m === 'live' && mode !== 'live') {
      setShowLiveConfirm(true);
      return;
    }
    await doModeSwitch(m);
  };

  const doModeSwitch = async (m: 'paper' | 'live') => {
    if (positions.length > 0) {
      return;
    }
    const res = await fetch(`/api/mode/${m}`, { method: 'POST' });
    const data = await res.json();
    if (!data.error) setMode(m);
    setShowLiveConfirm(false);
  };

  const handleSave = async () => {
    try {
      await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          daily_loss_limit: dailyLossLimit,
          max_positions: maxPositions,
          strategies: {
            CONTINUATION_BREAK: enableCont,
            MEAN_REVERSION: enableMR,
            EARLY_MOMENTUM: enableEM,
          },
        }),
      });
      onClose();
    } catch {
      // silently ignore
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <span>Settings</span>
          <button className="btn" onClick={onClose}>
            ✕
          </button>
        </div>

        {/* 1. Mode */}
        <section className="settings-section">
          <h4>Trading Mode</h4>
          <div className="tabs">
            <button
              className={`tab-btn ${mode === 'paper' ? 'active' : ''}`}
              onClick={() => handleModeSwitch('paper')}
            >
              PAPER
            </button>
            <button
              className={`tab-btn ${mode === 'live' ? 'active-live' : ''}`}
              onClick={() => handleModeSwitch('live')}
            >
              LIVE
            </button>
          </div>
          {positions.length > 0 && (
            <div style={{ fontSize: 10, color: 'var(--orange)', marginTop: 4 }}>
              Close all positions before switching mode
            </div>
          )}
          {showLiveConfirm && (
            <div className="live-confirm">
              <p style={{ fontSize: 12, color: 'var(--orange)', marginBottom: 8 }}>
                ⚠ You are about to switch to LIVE trading with real funds. Are you sure?
              </p>
              <button className="btn btn-danger" onClick={() => doModeSwitch('live')}>
                Confirm LIVE
              </button>
              <button className="btn" onClick={() => setShowLiveConfirm(false)} style={{ marginLeft: 8 }}>
                Cancel
              </button>
            </div>
          )}
        </section>

        {/* 2. Position Sizing */}
        <section className="settings-section">
          <h4>Position Sizing</h4>
          <SizeSettings />
        </section>

        {/* 3. Symbols */}
        <section className="settings-section">
          <h4>Symbols ({symbols.length})</h4>
          <div style={{ fontSize: 11, color: 'var(--text-secondary)' }}>
            {symbols.join(', ') || 'None configured'}
          </div>
        </section>

        {/* 4. Strategies */}
        <section className="settings-section">
          <h4>Strategies</h4>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={enableCont}
              onChange={(e) => setEnableCont(e.target.checked)}
            />
            Continuation Break
          </label>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={enableMR}
              onChange={(e) => setEnableMR(e.target.checked)}
            />
            Mean Reversion
          </label>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={enableEM}
              onChange={(e) => setEnableEM(e.target.checked)}
            />
            Early Momentum
          </label>
        </section>

        {/* 5. Risk */}
        <section className="settings-section">
          <h4>Risk Management</h4>
          <div className="settings-row">
            <label className="settings-label">Daily Loss Limit (%)</label>
            <input
              type="number"
              className="input-field"
              value={dailyLossLimit}
              min={1}
              max={50}
              onChange={(e) => setDailyLossLimit(Number(e.target.value))}
            />
          </div>
          <div className="settings-row">
            <label className="settings-label">Max Open Positions</label>
            <input
              type="number"
              className="input-field"
              value={maxPositions}
              min={1}
              max={20}
              onChange={(e) => setMaxPositions(Number(e.target.value))}
            />
          </div>
        </section>

        {/* 6. Leverage */}
        <section className="settings-section">
          <h4>Leverage</h4>
          <div className="settings-row">
            <label className="settings-label">Leverage</label>
            <span style={{ fontWeight: 600 }}>25x (fixed)</span>
          </div>
        </section>

        {/* 7. API Keys */}
        <section className="settings-section">
          <h4>API Keys</h4>
          <div className="settings-row">
            <label className="settings-label">API Key</label>
            <input
              type="password"
              className="input-field"
              value={apiKey}
              placeholder="Enter API key"
              onChange={(e) => setApiKey(e.target.value)}
            />
          </div>
          <div className="settings-row">
            <label className="settings-label">API Secret</label>
            <input
              type="password"
              className="input-field"
              value={apiSecret}
              placeholder="Enter API secret"
              onChange={(e) => setApiSecret(e.target.value)}
            />
          </div>
        </section>

        {/* 8. Notifications */}
        <section className="settings-section">
          <h4>Notifications</h4>
          <div className="settings-row">
            <label className="settings-label">Telegram Bot Token</label>
            <input
              type="password"
              className="input-field"
              value={telegramToken}
              placeholder="Enter Telegram bot token"
              onChange={(e) => setTelegramToken(e.target.value)}
            />
          </div>
          <div className="settings-row">
            <label className="settings-label">Telegram Chat ID</label>
            <input
              type="text"
              className="input-field"
              value={telegramChatId}
              placeholder="Enter chat ID"
              onChange={(e) => setTelegramChatId(e.target.value)}
            />
          </div>
        </section>

        {/* Buttons */}
        <div className="modal-actions">
          <button className="btn" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary" onClick={handleSave}>
            Save
          </button>
        </div>
      </div>
    </div>
  );
};
