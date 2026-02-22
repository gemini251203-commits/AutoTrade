<script setup lang="ts">
/**
 * GridDashboard.vue - 网格交易独立管理页面
 * ==========================================
 * 复用 GridTrading 组件，添加页面级 Header 和统计概览
 *
 * 注意: GridTrading.vue 组件完全不修改，Wallet.vue 中的引用也保持不变
 */

import { ref, onMounted, computed } from 'vue'
import { NIcon } from 'naive-ui'
import { GridOutline, RefreshOutline } from '@vicons/ionicons5'
import MainLayout from '@/layouts/MainLayout.vue'
import GridTrading from '@/components/GridTrading.vue'
import { listGridBots, type GridResponse } from '@/api/grid'

// ==================== State ====================
const bots = ref<GridResponse[]>([])
const loading = ref(false)

// ==================== Computed ====================
const runningCount = computed(() => bots.value.filter(b => b.status === 'running').length)
const totalProfit = computed(() => {
  return bots.value.reduce((sum, b) => sum + parseFloat(b.total_profit || '0'), 0)
})
const totalMatched = computed(() => {
  return bots.value.reduce((sum, b) => sum + (b.matched_count || 0), 0)
})

const totalInvestment = computed(() => {
  return bots.value.reduce((sum, b) => sum + parseFloat(b.investment || '0'), 0)
})

const activeBots = computed(() => {
  return bots.value.filter(b => b.status === 'running' || b.status === 'paused')
})

// ==================== Methods ====================
async function fetchOverview() {
  loading.value = true
  try {
    bots.value = await listGridBots()
  } catch {
    // GridTrading 组件会自行获取数据，这里仅用于统计概览
  } finally {
    loading.value = false
  }
}

onMounted(fetchOverview)
</script>

<template>
  <MainLayout>
    <div class="grid-page">
      <!-- Page Header -->
      <div class="page-header fade-in">
        <div class="header-left">
          <div class="header-icon">
            <NIcon :component="GridOutline" :size="24" />
          </div>
          <div>
            <h1>网格交易</h1>
            <p class="subtitle">自动高抛低吸 · 区间震荡策略</p>
          </div>
        </div>
        <button class="btn btn-ghost" @click="fetchOverview" :disabled="loading">
          <NIcon :component="RefreshOutline" :size="16" />
          刷新
        </button>
      </div>

      <!-- Overview Stats -->
      <div class="overview-stats" v-if="bots.length > 0">
        <div class="ov-card">
          <span class="ov-num">{{ bots.length }}</span>
          <span class="ov-label">总网格</span>
        </div>
        <div class="ov-divider" />
        <div class="ov-card">
          <span class="ov-num" style="color: #22c55e;">{{ runningCount }}</span>
          <span class="ov-label">运行中</span>
        </div>
        <div class="ov-divider" />
        <div class="ov-card">
          <span class="ov-num">{{ totalMatched }}</span>
          <span class="ov-label">总配对</span>
        </div>
        <div class="ov-divider" />
        <div class="ov-card">
          <span class="ov-num" :style="{ color: totalProfit >= 0 ? '#22c55e' : '#ef4444' }">
            {{ totalProfit >= 0 ? '+' : '' }}{{ totalProfit.toFixed(2) }}
          </span>
          <span class="ov-label">总收益 USDT</span>
        </div>
      </div>

      <!-- Investment Distribution -->
      <div class="distribution-panel" v-if="activeBots.length > 0">
        <h3 class="dist-title">运行中网格资金分布</h3>
        <div class="dist-bar-container">
          <div 
            v-for="bot in activeBots" 
            :key="bot.id"
            class="dist-segment"
            :style="{
              width: `${(parseFloat(bot.investment || '0') / totalInvestment) * 100}%`,
              background: `linear-gradient(135deg, hsl(${Math.abs(bot.id * 50) % 360}, 70%, 60%), hsl(${Math.abs(bot.id * 50) % 360}, 70%, 40%))`
            }"
            :title="`${bot.symbol} - ${bot.investment} USDT (${((parseFloat(bot.investment || '0') / totalInvestment) * 100).toFixed(1)}%)`"
          >
            <span class="segment-label">{{ bot.symbol }}</span>
          </div>
        </div>
        <div class="dist-legend">
          总投入: <span class="mono" style="color:#e5e7eb">{{ totalInvestment.toFixed(2) }} USDT</span>
        </div>
      </div>

      <!-- Grid Trading Component (复用) -->
      <GridTrading />
    </div>
  </MainLayout>
</template>

<style scoped>
.grid-page {
  max-width: 1400px;
  margin: 0 auto;
  padding-bottom: 40px;
}

/* Header */
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 28px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.header-icon {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  background: linear-gradient(135deg, #ec4899 0%, #a855f7 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
}

.header-left h1 {
  font-size: 22px;
  font-weight: 700;
  color: #f0f0f0;
  margin: 0;
}

.subtitle {
  font-size: 13px;
  color: #6b7280;
  margin: 0;
}

.btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.04);
  color: #9ca3af;
  cursor: pointer;
  font-size: 13px;
  transition: all 0.2s;
}

.btn:hover {
  background: rgba(255, 255, 255, 0.08);
  color: #e5e7eb;
}

/* Overview Stats */
.overview-stats {
  display: flex;
  align-items: center;
  gap: 20px;
  padding: 14px 20px;
  background: rgba(255, 255, 255, 0.02);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 10px;
  margin-bottom: 20px;
}

.ov-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}

.ov-num {
  font-size: 20px;
  font-weight: 700;
  font-family: 'SF Mono', monospace;
  color: #e5e7eb;
}

.ov-label {
  font-size: 11px;
  color: #6b7280;
}

.ov-divider {
  width: 1px;
  height: 32px;
  background: rgba(255, 255, 255, 0.08);
}

/* Distribution Panel */
.distribution-panel {
  padding: 16px 20px;
  background: rgba(255, 255, 255, 0.02);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 10px;
  margin-bottom: 24px;
}

.dist-title {
  font-size: 13px;
  color: #9ca3af;
  margin: 0 0 12px 0;
  font-weight: 500;
}

.dist-bar-container {
  height: 24px;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.04);
  display: flex;
  overflow: hidden;
  margin-bottom: 8px;
}

.dist-segment {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 0;
  cursor: pointer;
  transition: opacity 0.2s;
}

.dist-segment:hover {
  opacity: 0.8;
}

.segment-label {
  font-size: 10px;
  color: white;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  padding: 0 4px;
  text-shadow: 0 1px 2px rgba(0,0,0,0.5);
}

.dist-legend {
  font-size: 12px;
  color: #6b7280;
  text-align: right;
  margin-top: 8px;
}

/* Animation */
.fade-in {
  animation: fadeIn 0.4s ease-out;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(-8px); }
  to { opacity: 1; transform: translateY(0); }
}

@media (max-width: 768px) {
  .grid-page {
    padding: 10px;
    padding-bottom: calc(5rem + env(safe-area-inset-bottom));
  }
  .overview-stats {
    flex-wrap: wrap;
    gap: 12px;
  }
  .ov-divider {
    display: none;
  }
}
</style>
