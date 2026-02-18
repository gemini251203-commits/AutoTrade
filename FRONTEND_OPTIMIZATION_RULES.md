# Frontend Visual Optimization Rules

Your task is to optimize the AutoTrade frontend for better visual aesthetics and user experience. Only CSS, styling, animations, and layout improvements are allowed. Do not modify any business logic.

---

## Strictly Prohibited (DO NOT MODIFY)

1. **All API functions** -- Do not modify any file under `frontend/src/api/`. Do not change function signatures, request paths, parameter names, or return types.
2. **All Store logic** -- Do not modify any action, getter, or state definition in `frontend/src/stores/auth.ts`, `wallet.ts`, `symbol.ts`.
3. **All route configuration** -- Do not modify `frontend/src/router/index.ts`. Do not change the route table, navigation guards, or meta fields.
4. **All backend files** -- Do not touch anything under `backend/`.
5. **Data binding logic** -- Do not modify `v-model`, `computed`, `watch`, `onMounted`, or any reactive data processing logic inside Vue components.
6. **Event handler internals** -- Do not modify the internal logic of `@click`, `@submit`, or any event handler functions. You may only change CSS classes or style bindings attached to them.
7. **Type definitions** -- Do not modify any file under `frontend/src/types/`.
8. **Request utility** -- Do not modify `frontend/src/utils/request.ts` (Axios interceptors and token refresh logic).
9. **Field name mapping** -- All `snake_case` field names (e.g. `total_pnl`, `unrealized_pnl`, `status_filter`, `trade_side`, `position_side`) are strictly mapped to backend Pydantic schemas. Do not rename, remap, or transform them.
10. **Component props/emit interfaces** -- Do not change the props or emits interface of any component.

---

## Allowed Modifications

1. **CSS styles** -- Everything inside `<style>` blocks: colors, spacing, fonts, border-radius, shadows, gradients, backdrop-filter, opacity.
2. **Naive UI theme overrides** -- The `themeOverrides` object in `NConfigProvider` (located in `App.vue`).
3. **Template DOM structure** -- You may adjust `<template>` DOM structure for layout purposes, but do not remove any element that has a data binding (v-model, v-if, v-for, @click, :value, etc.).
4. **CSS animations and transitions** -- Add `transition`, `animation`, `@keyframes`, hover effects, focus effects.
5. **Layout optimization** -- Adjust flex/grid layouts, responsive breakpoints, spacing ratios, container widths.
6. **Font imports** -- You may import Google Fonts or other web fonts.
7. **Icon changes** -- You may replace or add icons.
8. **Loading/skeleton states** -- You may improve the visual presentation of loading indicators and skeleton screens.
9. **Micro-interactions** -- Add subtle hover animations, button press feedback, card hover elevation, smooth scrolling.

---

## Tech Stack

- Vue 3 + Composition API (`<script setup>` syntax)
- Naive UI component library (dark theme)
- Pinia state management
- TypeScript
- Vite build tool
- Current theme: dark mode, purple accent color palette

---

## File Structure

```
frontend/src/
  api/          -- API functions (DO NOT MODIFY)
  components/   -- Reusable components:
                   AccountMenu.vue, GridTrading.vue, OrderList.vue,
                   PositionList.vue, SkeletonCard.vue, TradePanel.vue,
                   TradingChart.vue
  layouts/      -- MainLayout.vue (sidebar + top bar)
  stores/       -- State management (DO NOT MODIFY logic)
  types/        -- Type definitions (DO NOT MODIFY)
  utils/        -- Utilities (DO NOT MODIFY)
  views/        -- Pages:
                   Admin.vue, AutopilotDashboard.vue, ChatAgent.vue,
                   Dashboard.vue, Login.vue, NewsCenter.vue,
                   Settings.vue, SignalAssistant.vue, StrategyManager.vue,
                   TradeJournal.vue, Wallet.vue
  App.vue       -- Root component (theme config can be modified)
  router/       -- Routing (DO NOT MODIFY)
```

---

## Verification Requirements

After every change, you must verify:

1. `npm run build` completes with zero errors.
2. All pages render correctly and all interactive elements remain functional (buttons clickable, forms submittable, data displays correctly).
3. No TypeScript compilation errors.
4. No runtime console errors related to missing data bindings or broken references.
