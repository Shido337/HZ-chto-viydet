import React, { useEffect, useRef } from 'react';
import { createChart, IChartApi, ISeriesApi, Time } from 'lightweight-charts';
import { useTradingStore } from '../store/tradingStore';

export const CVDPanel: React.FC = () => {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<'Area'> | null>(null);

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
      height: 120,
      timeScale: { timeVisible: true, secondsVisible: false },
      rightPriceScale: { visible: true },
    });
    const series = chart.addAreaSeries({
      topColor: 'rgba(0, 212, 255, 0.3)',
      bottomColor: 'rgba(255, 68, 102, 0.3)',
      lineColor: '#00d4ff',
      lineWidth: 1,
    });
    chartRef.current = chart;
    seriesRef.current = series;

    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        chart.applyOptions({ width: entry.contentRect.width });
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
    const klines = snap.klines_1m;
    if (!klines?.length) return;
    let cumDelta = 0;
    const data = klines.map((k) => {
      cumDelta += k.v * (k.c > k.o ? 1 : -1);
      return { time: (k.t / 1000) as Time, value: cumDelta };
    });
    seriesRef.current.setData(data);
  }, [snap]);

  return (
    <div className="cvd-container">
      <div style={{ padding: '2px 8px', fontSize: 11, color: 'var(--text-secondary)' }}>
        CVD {symbol}
      </div>
      <div ref={containerRef} style={{ height: 100 }} />
    </div>
  );
};
