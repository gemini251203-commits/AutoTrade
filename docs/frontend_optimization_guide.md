# AutoTrade 前端优化指南 (Gemini 专用)

> **目的**: 本文档为后续 Gemini 任务提供前端修改约束，确保不破坏现有逻辑。

## 核心原则

1. **增量添加，不修改** — 所有已有函数、computed、生命周期钩子不可修改其语义
2. **零 API 膨胀** — 新增前端功能优先用 computed/watch 计算已有数据，不随意新增后端 API
3. **组件复用** — 已有组件优先 import 复用，不重新实现

## 技术栈约束

| 项目 | 值 |
|------|-----|
| Vue | 3 + `<script setup lang="ts">` |
| CSS | TailwindCSS v4 (`@import "tailwindcss"`) + scoped CSS |
| UI 库 | Naive UI (NIcon, NTag, NButton, NSelect, NSpin, NEmpty 等) |
| 配色 | 暗黑赛博朋克 (`--color-dark-bg: #0a0a0f`, `--color-dark-card: #141420`) |
| 字体 | Inter + SF Mono / JetBrains Mono |
| 图标 | `@vicons/ionicons5` |

## 页面清单与负责人

| 路由 | 文件 | 职责 | 修改风险 |
|------|------|------|---------|
| `/` | `Dashboard.vue` | 主控制台 | ⚠️ 高 |
| `/chat` | `ChatAgent.vue` | AI 对话 | ⚠️ 高 (SSE 流式) |
| `/journal` | `TradeJournal.vue` | 交易日志 | 🟡 中 |
| `/autopilot` | `AutopilotDashboard.vue` | AI Autopilot | 🟡 中 |
| `/grid` | `GridDashboard.vue` | 网格交易 (独立页，复用 GridTrading) | 🟢 低 |
| `/pipeline` | `PipelineMonitor.vue` | 流水线监控 | 🟡 中 |
| `/strategy` | `StrategyManager.vue` | 策略管理 | 🟢 低 |
| `/wallet` | `Wallet.vue` | 钱包 (含 GridTrading 组件) | ⚠️ 高 |
| `/signal` | `SignalAssistant.vue` | 信号助手 | 🟢 低 |
| `/settings` | `Settings.vue` | 设置 | 🟢 低 |

## 关键组件的不可修改函数

### TradeJournal.vue
- `fetchAll()` — 使用 `/journal/` + `/journal/stats` API，过滤逻辑不变
- `onFilterChange()` — 直接调用 fetchAll
- `deleteMemory()` — DELETE API
- `sourceColors` / `sourceLabels` — 所有来源的颜色和标签映射
- **可安全扩展**: 新增 computed 做统计、新增 CSS 区块

### AutopilotDashboard.vue
- `pollStatus()` — 定时轮询状态
- `fetchLogs()` — 获取决策日志
- `handleStart()` / `handleStop()` / `handleRunOnce()` — 启停控制
- `decisionColors` / `decisionLabels` — 决策类型的颜色和标签
- **可安全扩展**: 新增 computed 统计、新增 HTML/CSS 面板

### GridTrading.vue (组件)
- 完整 CRUD 生命周期：`fetchGridBots()` → `createGrid()` → `startGrid()` → `stopGrid()` → `deleteGrid()`
- **不可修改**: 组件自身逻辑。可在 GridDashboard.vue 页面级扩展

### PipelineMonitor.vue
- `fetchStatus()` — 5 秒轮询
- `handleCircuitBreaker()` — 熔断器控制
- **可安全扩展**: 新增统计面板、增加图表

## 新增页面的标准模式

```vue
<script setup lang="ts">
import MainLayout from '@/layouts/MainLayout.vue'
// ... imports

// State, Computed, Methods
</script>

<template>
  <MainLayout>
    <div class="page-name">
      <!-- Page Header -->
      <!-- Content -->
    </div>
  </MainLayout>
</template>

<style scoped>
/* Follow existing dark theme patterns */
</style>
```

## API 文件对照

| API 文件 | 后端路径 | 适用页面 |
|---------|---------|---------|
| `api/chat.ts` | `/agent/*` | ChatAgent, AutopilotDashboard |
| `api/grid.ts` | `/grid/*` | GridTrading, GridDashboard |
| `api/pipeline.ts` | `/pipeline/*` | PipelineMonitor |
| `api/strategy.ts` | `/strategy/*` | StrategyManager, TradeJournal |
| `utils/request.ts` | Axios 实例 | 所有 |

## 后续优化方向

1. **TradeJournal**: 可加入时间范围筛选、导出 CSV、交易对维度分析
2. **AutopilotDashboard**: 可加入交易对切换筛选日志、AI 决策置信度图表
3. **GridDashboard**: 可加入网格价格梯度可视化、与 AI Agent 联动建议
4. **PipelineMonitor**: 可加入历史 insights/verdicts 趋势图、风控规则实时查看
5. **整体**: 可加入 WebSocket 实时推送替代轮询
