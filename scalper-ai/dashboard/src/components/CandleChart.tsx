import React, { useEffect, useRef, useState } from 'react';
import { createChart, IChartApi, ISeriesApi, CandlestickData, Time, PriceLineOptions, LineStyle } from 'lightweight-charts';
import { useTradingStore } from '../store/tradingStore';

type TF = '1m' | '3m' | '5m';

export const CandleChart: React.FC = () => {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const priceLinesRef = useRef<any[]>([]);
  const [tf, setTf] = useState<TF>('1m');

  const symbol = useTradingStore((s) => s.selectedSymbol);
  const snap = useTradingStore((s) => s.snapshots[symbol]);
  const positions = useTradingStore((s) => s.positions);
  const pendingOrders = useTradingStore((s) => s.pendingOrders);

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

  // Full data load on symbol or timeframe change
  const prevSymRef = useRef('');
  const prevTfRef = useRef('');
  const dataLoadedRef = useRef(false);
  const fetchingRef = useRef('');
  useEffect(() => {
    if (!seriesRef.current || !snap) return;
    const klines =
      tf === '1m' ? snap.klines_1m : tf === '3m' ? snap.klines_3m : snap.klines_5m;

    // Fetch klines via REST if missing (e.g. after symbol rotation or partial load)
    if (!klines?.length) {
      const fetchKey = `${symbol}_${tf}`;
      if (fetchingRef.current !== fetchKey) {
        fetchingRef.current = fetchKey;
        fetch(`/api/klines/${symbol}`)
          .then((r) => r.json())
          .then((data) => {
            const store = useTradingStore.getState();
            store.setSnapshot(data);
          })
          .catch(() => {})
          .finally(() => { fetchingRef.current = ''; });
      }
      return;
    }

    // Full setData on first load or symbol/tf change
    if (!dataLoadedRef.current || prevSymRef.current !== symbol || prevTfRef.current !== tf) {
      prevSymRef.current = symbol;
      prevTfRef.current = tf;
      dataLoadedRef.current = true;
      const data: CandlestickData[] = klines.map((k) => ({
        time: (k.t / 1000) as Time,
        open: k.o,
        high: k.h,
        low: k.l,
        close: k.c,
      }));
      seriesRef.current.setData(data);
      chartRef.current?.timeScale().fitContent();
    } else {
      // Incremental update — only the last candle
      const last = klines[klines.length - 1];
      if (last) {
        seriesRef.current.update({
          time: (last.t / 1000) as Time,
          open: last.o,
          high: last.h,
          low: last.l,
          close: last.c,
        });
      }
    }
  }, [snap, tf, symbol]);

  // -- Price level lines (Entry / SL / TP / Trailing) ----------------------
  useEffect(() => {
    const series = seriesRef.current;
    if (!series) return;

    // Remove previously created price lines
    for (const line of priceLinesRef.current) {
      series.removePriceLine(line);
    }
    priceLinesRef.current = [];

    // Active position for selected symbol
    const pos = positions.find((p) => p.symbol === symbol);
    if (pos) {
      const base: Partial<PriceLineOptions> = {
        axisLabelVisible: true,
        lineWidth: 1,
      };
      const addLine = (opts: PriceLineOptions) => {
        priceLinesRef.current.push(series.createPriceLine(opts));
      };
      addLine({
        ...base,
        price: pos.entry_price,
        color: '#ffaa00',
        lineStyle: LineStyle.Solid,
        title: `ENTRY ${pos.direction}`,
      } as PriceLineOptions);
      addLine({
        ...base,
        price: pos.sl_price,
        color: '#ff4466',
        lineStyle: pos.breakeven_moved ? LineStyle.Solid : LineStyle.Dashed,
        title: pos.breakeven_moved ? 'BE' : 'SL',
      } as PriceLineOptions);
      addLine({
        ...base,
        price: pos.tp_price,
        color: '#00d4aa',
        lineStyle: LineStyle.Dashed,
        title: 'TP',
      } as PriceLineOptions);
      // Trailing stop line (only when trailing is active)
      if (pos.trailing_activated && pos.best_price > 0) {
        const TRAILING_PCT = 0.0015;
        const trailSl =
          pos.direction === 'LONG'
            ? pos.best_price * (1 - TRAILING_PCT)
            : pos.best_price * (1 + TRAILING_PCT);
        if (Math.abs(trailSl - pos.sl_price) > pos.entry_price * 0.00001) {
          addLine({
            ...base,
            price: trailSl,
            color: '#ff88ff',
            lineStyle: LineStyle.Dotted,
            title: 'TRAIL',
          } as PriceLineOptions);
        }
      }
    }

    // Pending limit order for selected symbol
    const pending = pendingOrders.find((o) => o.symbol === symbol);
    if (pending) {
      priceLinesRef.current.push(
        series.createPriceLine({
          price: pending.price,
          color: '#ffaa00',
          lineStyle: LineStyle.Dotted,
          axisLabelVisible: true,
          lineWidth: 1,
          title: `LIMIT ${pending.direction}`,
        } as PriceLineOptions),
      );
    }
  }, [positions, pendingOrders, symbol]);

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
