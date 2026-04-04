import React, { useEffect, useRef, useState } from 'react';
import { createChart, IChartApi, ISeriesApi, CandlestickData, Time } from 'lightweight-charts';
import { useTradingStore } from '../store/tradingStore';

type TF = '1m' | '3m' | '5m';

export const CandleChart: React.FC = () => {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const [tf, setTf] = useState<TF>('1m');

  const symbol = useTradingStore((s) => s.selectedSymbol);
  const snap = useTradingStore((s) => s.snapshots[symbol]);

  useEffect(() => {
    if (!containerRef.current) return;
    const chart = createChart(containerRef.current, {
      layout: { background: { color: '#0a0a1a' }, textColor: '#8888aa' },
      grid: {
        vertLines: { color: '#1a1a3a' },
        horzLines: { color: '#1a1a3a' },
      },
      width: containerRef.current.clientWidth,
      height: containerRef.current.clientHeight,
      crosshair: { mode: 0 },
      timeScale: { timeVisible: true, secondsVisible: false },
    });
    const series = chart.addCandlestickSeries({
      upColor: '#00d4aa',
      downColor: '#ff4466',
      wickUpColor: '#00d4aa',
      wickDownColor: '#ff4466',
      borderVisible: false,
    });
    chartRef.current = chart;
    seriesRef.current = series;

    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        chart.applyOptions({
          width: entry.contentRect.width,
          height: entry.contentRect.height,
        });
      }
    });
    ro.observe(containerRef.current);
    return () => {
      ro.disconnect();
      chart.remove();
    };
  }, []);

  useEffect(() => {
    if (!seriesRef.current || !snap) return;
    const klines =
      tf === '1m' ? snap.klines_1m : tf === '3m' ? snap.klines_3m : snap.klines_5m;
    if (!klines?.length) return;
    const data: CandlestickData[] = klines.map((k) => ({
      time: (k.t / 1000) as Time,
      open: k.o,
      high: k.h,
      low: k.l,
      close: k.c,
    }));
    seriesRef.current.setData(data);
  }, [snap, tf]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1 }}>
      <div style={{ display: 'flex', alignItems: 'center', padding: '4px 8px', gap: 8 }}>
        <span style={{ fontWeight: 700, color: 'var(--cyan)' }}>
          {symbol.replace('USDT', '/USDT')}
        </span>
        <div className="tf-switcher">
          {(['1m', '3m', '5m'] as TF[]).map((t) => (
            <button
              key={t}
              className={`tf-btn ${tf === t ? 'active' : ''}`}
              onClick={() => setTf(t)}
            >
              {t}
            </button>
          ))}
        </div>
      </div>
      <div ref={containerRef} className="chart-container" />
    </div>
  );
};
