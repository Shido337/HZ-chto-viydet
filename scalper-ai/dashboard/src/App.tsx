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
import { TradeHistory } from './components/TradeHistory';

export const App: React.FC = () => {
  useWebSocket();
  const settingsOpen = useTradingStore((s) => s.settingsOpen);
  const tradeHistoryOpen = useTradingStore((s) => s.tradeHistoryOpen);
  const setSettingsOpen = useTradingStore((s) => s.setSettingsOpen);
  const setTradeHistoryOpen = useTradingStore((s) => s.setTradeHistoryOpen);

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
          <div className="chart-area">
            <CandleChart />
            <CVDPanel />
          </div>
          <div className="tables-area">
            <OpenPositions />
            <PendingLimitsTable />
          </div>
        </div>
        <div className="right-panel">
          <ActiveSignals />
          <EquityCurve />
          <Monitor />
        </div>
      </div>
      <SettingsModal open={settingsOpen} onClose={() => setSettingsOpen(false)} />
      <TradeHistory open={tradeHistoryOpen} onClose={() => setTradeHistoryOpen(false)} />
    </>
  );
};
