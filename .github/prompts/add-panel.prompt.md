---
description: "Add a new dashboard panel/component to the SCALPER-AI React dashboard. Handles component creation, store integration, and CSS."
---

# Add Dashboard Panel

## Inputs
- **Component Name**: e.g. `TradeHistory`
- **Panel Position**: left, center, or right
- **Data Source**: Which store fields it reads

## Steps

1. Create `scalper-ai/dashboard/src/components/{{ComponentName}}.tsx`:
   - Functional component with typed props
   - Import from `../store/tradingStore`
   - Follow existing panel pattern (`.panel` wrapper, `.panel-header`)

2. Add to `scalper-ai/dashboard/src/App.tsx`:
   - Import the component
   - Place in the correct panel (left/center/right)

3. If new data types needed:
   - Add to `types/index.ts`
   - Add to `tradingStore.ts` state + actions
   - Add WsEvent variant if backend pushes this data

4. Add CSS in `index.css`:
   - Use CSS variables (`var(--cyan)`, `var(--bg-panel)`)
   - No hardcoded colors

5. If backend data needed:
   - Add FastAPI endpoint in `server/api.py`
   - Add WS event type in `ws_manager.py` broadcast
