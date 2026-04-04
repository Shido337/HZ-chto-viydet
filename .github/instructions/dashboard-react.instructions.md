---
description: "Use when writing or modifying React/TypeScript dashboard code in scalper-ai/dashboard/. Covers component patterns, Zustand store, WebSocket events, TradingView charts, and dark theme styling."
applyTo: ["scalper-ai/dashboard/**/*.tsx", "scalper-ai/dashboard/**/*.ts", "scalper-ai/dashboard/**/*.css"]
---

# TypeScript/React Standards — SCALPER-AI Dashboard

## Components

- Functional components only — no class components
- Export as named: `export const MyComponent: React.FC<Props> = ...`
- Props interface defined above each component
- No prop drilling beyond 2 levels — use Zustand store

## TypeScript

- Strict mode — no `any`, no implicit returns
- All types in `types/index.ts`: Signal, Position, Trade, MarketSnapshot, WsEvent, etc.
- Use discriminated union `WsEvent` for all WebSocket message types

## State Management — Zustand

- Single store in `store/tradingStore.ts`
- Typed slices, no direct state mutation
- Derived values as methods: `winRate()`, `profitFactor()`, `totalTrades()`
- Store updates only through store actions, never direct `set()`

## WebSocket

- `hooks/useWebSocket.ts` handles connection + auto-reconnect (3s delay)
- All WS events routed through `handleEvent()` switch
- Store actions called from event handler — no business logic in hook
- Events: market_snapshot, signal_new, signal_expired, position_opened, position_updated, trade_closed, balance_update, regime_update

## Charts

- TradingView Lightweight Charts for candles + CVD
- Recharts for equity curve
- Dark theme: `#0a0a1a` background, `#00d4aa` green, `#ff6b35` orange, `#00d4ff` cyan
- Use ResizeObserver for responsive charts

## Styling

- CSS variables in `:root` for all theme colors — never hardcoded hex in components
- Dark theme: `--bg-primary: #060612`, `--bg-panel: #0a0a1a`
- Accent colors: `--cyan`, `--green`, `--red`, `--orange`
- Class naming: BEM-like (`panel-header`, `coin-item`, `direction-badge`)

## API Calls

- Vite proxy: `/api` → `http://localhost:8000`, `/ws` → WebSocket
- Use `fetch()` for REST, no axios
- POST with `Content-Type: application/json`
