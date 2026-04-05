import React, { useEffect, useRef, useState } from 'react';
import {
  createChart, IChartApi, ISeriesApi,
  CandlestickData, Time, PriceLineOptions, LineStyle,
} from 'lightweight-charts';
import { useTradingStore } from '../store/tradingStore';

type TF = '1m' | '3m' | '5m';

const CANDLE_OPTS = {
  upColor: '#00d4aa',
  downColor: '#ff4466',
  wickUpColor: '#00d4aa',
  wickDownColor: '#ff4466',
  borderVisible: false,
};

export const CandleChart: React.FC = () => {
  const containerRef  = useRef<HTMLDivElement>(null);
  const chartRef      = useRef<IChartApi | null>(null);
  const seriesRef     = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const priceLinesRef = useRef<any[]>([]);

  const [tf, setTf] = useState<TF>('1m');
  // Fetched candles stored in state — rendering effect reads from here
  const [fetchedData, setFetchedData] = useState<{ key: string; bars: CandlestickData[] } | null>(null);

  const symbol        = useTradingStore((s) => s.selectedSymbol);
  const snap          = useTradingStore((s) => s.snapshots[symbol]);
  const positions     = useTradingStore((s) => s.positions);
  const pendingOrders = useTradingStore((s) => s.pendingOrders);

  // ── 1. Create chart once ────────────────────────────────────────────────
  useEffect(() => {
    if (!containerRef.current) return;
    const w = containerRef.current.clientWidth  || 600;
    const h = containerRef.current.clientHeight || 400;
    const chart = createChart(containerRef.current, {
      layout: { background: { color: '#0a0a1a' }, textColor: '#8888aa' },
      grid: { vertLines: { color: '#1a1a3a' }, horzLines: { color: '#1a1a3a' } },
      crosshair: { mode: 0 },
      timeScale: { timeVisible: true, secondsVisible: false },
      width: w,
      height: h,
    });
    const series = chart.addCandlestickSeries(CANDLE_OPTS);
    chartRef.current  = chart;
    seriesRef.current = series;

    const ro = new ResizeObserver(([entry]) => {
      if (chartRef.current) {
        chartRef.current.applyOptions({
          width:  entry.contentRect.width,
          height: entry.contentRect.height,
        });
      }
    });
    ro.observe(containerRef.current);

    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current  = null;
      seriesRef.current = null;
    };
  }, []);

  // ── 2. Fetch klines → store in state (no chart access here) ────────────
  useEffect(() => {
    if (!symbol) return;
    setFetchedData(null);
    // Clear chart immediately so stale symbol data doesn't linger during fetch
    if (seriesRef.current) seriesRef.current.setData([]);
    let cancelled = false;
    fetch(`/api/klines/${symbol}`)
      .then((r) => { if (!r.ok) throw new Error(`${r.status}`); return r.json(); })
      .then((data) => {
        if (cancelled) return;
        useTradingStore.getState().setSnapshot(data);
        const raw: any[] =
          tf === '1m' ? data.klines_1m
          : tf === '3m' ? data.klines_3m
          : data.klines_5m;
        if (!raw?.length) return;
        const bars: CandlestickData[] = raw.map((k) => ({
          time: (k.t / 1000) as Time,
          open: k.o, high: k.h, low: k.l, close: k.c,
        }));
        setFetchedData({ key: `${symbol}:${tf}`, bars });
      })
      .catch((e) => console.error('[CandleChart] fetch failed', e));
    return () => { cancelled = true; };
  }, [symbol, tf]);

  // ── 3. Render fetched data to chart (runs after state update) ──────────
  useEffect(() => {
    if (!fetchedData || !seriesRef.current || !chartRef.current) return;
    seriesRef.current.setData(fetchedData.bars);
    chartRef.current.timeScale().fitContent();
  }, [fetchedData]);

  // ── 4. Incremental update from WS ──────────────────────────────────────
  useEffect(() => {
    if (!seriesRef.current || !snap || !fetchedData) return;
    if (fetchedData.key !== `${symbol}:${tf}`) return;
    const klines =
      tf === '1m' ? snap.klines_1m
      : tf === '3m' ? snap.klines_3m
      : snap.klines_5m;
    if (!klines?.length) return;
    const last = klines[klines.length - 1];
    if (!last) return;
    seriesRef.current.update({
      time: (last.t / 1000) as Time,
      open: last.o, high: last.h, low: last.l, close: last.c,
    });
  }, [snap, tf, symbol, fetchedData]);

  // ── 5. Price lines (Entry / SL / TP / Trailing / Pending) ──────────────
  useEffect(() => {
    const series = seriesRef.current;
    if (!series) return;

    for (const line of priceLinesRef.current) series.removePriceLine(line);
    priceLinesRef.current = [];

    const add = (opts: PriceLineOptions) =>
      priceLinesRef.current.push(series.createPriceLine(opts));

    const pos = positions.find((p) => p.symbol === symbol);
    if (pos) {
      const base = { axisLabelVisible: true, lineWidth: 1 } as const;
      add({ ...base, price: pos.entry_price, color: '#ffaa00', lineStyle: LineStyle.Solid,  title: `ENTRY ${pos.direction}` } as PriceLineOptions);
      add({ ...base, price: pos.sl_price,    color: '#ff4466', lineStyle: pos.breakeven_moved ? LineStyle.Solid : LineStyle.Dashed, title: pos.breakeven_moved ? 'BE' : 'SL' } as PriceLineOptions);
      add({ ...base, price: pos.tp_price,    color: '#00d4aa', lineStyle: LineStyle.Dashed, title: 'TP' } as PriceLineOptions);

      if (pos.trailing_activated && pos.best_price > 0) {
        const TRAIL = 0.0015;
        const trailSl = pos.direction === 'LONG'
          ? pos.best_price * (1 - TRAIL)
          : pos.best_price * (1 + TRAIL);
        if (Math.abs(trailSl - pos.sl_price) > pos.entry_price * 0.00001) {
          add({ ...base, price: trailSl, color: '#ff88ff', lineStyle: LineStyle.Dotted, title: 'TRAIL' } as PriceLineOptions);
        }
      }
    }

    const pending = pendingOrders.find((o) => o.symbol === symbol);
    if (pending) {
      add({ price: pending.price, color: '#ffaa00', lineStyle: LineStyle.Dotted, axisLabelVisible: true, lineWidth: 1, title: `LIMIT ${pending.direction}` } as PriceLineOptions);
    }
  }, [positions, pendingOrders, symbol]);

  // ── Render ──────────────────────────────────────────────────────────────
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
