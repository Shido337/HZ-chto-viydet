import React from 'react';
import { useWebSocket } from './hooks/useWebSocket';
import { useTradingStore } from './store/tradingStore';
import { TopBar } from './components/TopBar';
import { CoinWatch } from './components/CoinWatch';
import { Performance } from './components/Performance';
import { Targets } from './components/Targets';
import { MLModel } from './components/MLModel';
import { OrderFlow } from './components/OrderFlow';
import { PendingLimits } from './components/PendingLimits';
import { CandleChart } from './components/CandleChart';
import { CVDPanel } from './components/CVDPanel';
import { OpenPositions } from './components/OpenPositions';
import { PendingLimitsTable } from './components/PendingLimitsTable';
import { ActiveSignals } from './components/ActiveSignals';
import { EquityCurve } from './components/EquityCurve';
import { Monitor } from './components/Monitor';
import { SettingsModal } from './components/SettingsModal';

export const App: React.FC = () => {
  useWebSocket();
  const settingsOpen = useTradingStore((s) => s.settingsOpen);

  const setSettingsOpen = useTradingStore((s) => s.setSettingsOpen);

  return (
    <>
      <TopBar />
      <div className="app-layout">
        <div className="left-panel">
          <CoinWatch />
          <Performance />
          <Targets />
          <MLModel />
          <OrderFlow />
          <PendingLimits />
        </div>
        <div className="center-panel">
          <CandleChart />
          <CVDPanel />
          <OpenPositions />
          <PendingLimitsTable />
        </div>
        <div className="right-panel">
          <ActiveSignals />
          <EquityCurve />
          <Monitor />
        </div>
      </div>
      <SettingsModal open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </>
  );
};
