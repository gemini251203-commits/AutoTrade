<script setup lang="ts">
/**
 * Dashboard.vue
 * ==============
 * 交易主界面
 * 
 * 底部 Tabs:
 * - 当前委托
 * - 仓位
 * - 网格交易 (自动高抛低吸)
 * - 历史委托
 */
import { ref, onMounted, onUnmounted } from 'vue'
import { NMessageProvider } from 'naive-ui'
import MainLayout from '@/layouts/MainLayout.vue'
import TradingChart from '@/components/TradingChart.vue'
import TradePanel from '@/components/TradePanel.vue'
import PositionList from '@/components/PositionList.vue'
import OrderList from '@/components/OrderList.vue'
import GridTrading from '@/components/GridTrading.vue'

type TabKey = 'orders' | 'positions' | 'grid' | 'order_history'

const activeTab = ref<TabKey>('positions')

const tabs: { key: TabKey; label: string; highlight?: boolean }[] = [
  { key: 'orders', label: '当前委托' },
  { key: 'positions', label: '仓位', highlight: true },
  { key: 'grid', label: '网格交易' },
  { key: 'order_history', label: '历史委托' },
]

// ========== Resizable Panel Logic ==========
const bottomHeight = ref(350)
const isResizing = ref(false)
const startY = ref(0)
const startH = ref(0)

function startResize(e: MouseEvent) {
  isResizing.value = true
  startY.value = e.clientY
  startH.value = bottomHeight.value
  document.body.style.cursor = 'row-resize'
  document.body.style.userSelect = 'none' // 禁止选中文字
  
  window.addEventListener('mousemove', handleMouseMove)
  window.addEventListener('mouseup', stopResize)
}

function handleMouseMove(e: MouseEvent) {
  if (!isResizing.value) return
  const delta = startY.value - e.clientY // 向上拖动增加高度
  const newHeight = startH.value + delta
  
  // 限制高度范围
  if (newHeight >= 200 && newHeight <= 800) {
    bottomHeight.value = newHeight
  }
}

function stopResize() {
  isResizing.value = false
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
  window.removeEventListener('mousemove', handleMouseMove)
  window.removeEventListener('mouseup', stopResize)
}
const showTradePanel = ref(false)
</script>

<template>
  <NMessageProvider>
    <MainLayout>
      <div class="dashboard-root flex flex-col gap-3 md:h-full">
        <!-- Top Section: Chart + Trade Panel -->
        <div class="grid grid-cols-1 md:grid-cols-12 gap-3 md:flex-1 md:min-h-0 md:overflow-visible">
          <!-- Chart Area -->
          <div 
            class="md:col-span-9 rounded-xl overflow-hidden glass-panel h-[45vh] md:h-auto min-h-[350px]"
            style="background: rgba(0, 0, 0, 0.4);"
          >
            <TradingChart />
          </div>
          
          <!-- Mobile Trade Toggle -->
          <button 
            class="md:hidden w-full py-3 rounded-xl glass-panel text-center text-sm font-medium active:scale-95 transition-transform"
            style="background: rgba(0, 0, 0, 0.4);"
            @click="showTradePanel = !showTradePanel"
          >
            {{ showTradePanel ? '▲ 收起交易面板' : '▼ 展开交易面板' }}
          </button>
          
          <!-- Trade Panel -->
          <div 
            class="md:col-span-3 rounded-xl overflow-hidden glass-panel transision-all duration-300"
            :class="showTradePanel ? 'block' : 'hidden md:block'"
            style="background: rgba(0, 0, 0, 0.4);"
          >
            <!-- Mobile: max-height limit to prevent taking over screen -->
            <div class="h-full max-h-[60vh] md:max-h-[600px] overflow-y-auto">
              <TradePanel />
            </div>
          </div>
        </div>
        
        <!-- Bottom Section: Tabs Panel -->
        <div 
          class="resizable-panel rounded-xl overflow-hidden flex flex-col relative glass-panel"
          style="background: rgba(0, 0, 0, 0.4);"
          :style="{ 
            height: bottomHeight + 'px',
            transition: isResizing ? 'none' : 'height 0.2s ease'
          }"
        >
          <!-- Resize Handle (Desktop only) -->
          <div 
            class="resize-handle hidden md:flex"
            @mousedown="startResize"
          >
            <div class="handle-bar"></div>
          </div>

          <!-- Tabs -->
          <div class="bottom-tabs">
            <button
              v-for="tab in tabs"
              :key="tab.key"
              @click="activeTab = tab.key"
              :class="['bottom-tab', activeTab === tab.key ? 'active' : '', tab.highlight ? 'highlight' : '']"
            >
              {{ tab.label }}
            </button>
          </div>
          
          <!-- Tab Content -->
          <div class="tab-content flex-1 overflow-y-auto custom-scrollbar">
            <OrderList v-if="activeTab === 'orders' || activeTab === 'order_history'" />
            <PositionList v-else-if="activeTab === 'positions'" />
            <GridTrading v-else-if="activeTab === 'grid'" />
          </div>
        </div>
      </div>
    </MainLayout>
  </NMessageProvider>
</template>

<style scoped>
/* Bottom Tabs Style */
.bottom-tabs {
  display: flex;
  gap: 0;
  border-bottom: 1px solid rgba(255,255,255,0.05);
  background: rgba(255, 255, 255, 0.02);
  flex-shrink: 0;
}

.bottom-tab {
  padding: 10px 16px;
  background: transparent;
  border: none;
  color: #6b7280;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s;
  position: relative;
  font-weight: 500;
}

.bottom-tab:hover {
  color: #d1d5db;
  background: rgba(255,255,255,0.03);
}

.bottom-tab.active {
  color: #ffffff;
  background: rgba(255,255,255,0.05);
}

.bottom-tab.highlight {
  color: #f97316;
}

.bottom-tab.highlight.active {
  color: #fb923c;
}

.bottom-tab.active::after {
  content: '';
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: 2px;
  background: #8a2be2;
  box-shadow: 0 -2px 5px rgba(138, 43, 226, 0.5);
}

.tab-content {
  /* min-height removed, handled by flex container */
  position: relative;
  background: transparent; /* Changed from #09090b to transparent */
}

/* Resize Handle */
.resize-handle {
  height: 8px;
  width: 100%;
  cursor: row-resize;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 255, 255, 0.02);
  border-bottom: 1px solid rgba(255,255,255,0.02);
  transition: background 0.2s;
}

.resize-handle:hover {
  background: rgba(255,255,255,0.05);
}

.handle-bar {
  width: 40px;
  height: 3px;
  background: rgba(255,255,255,0.1);
  border-radius: 2px;
}

.resize-handle:hover .handle-bar {
  background: #8a2be2;
}

/* Custom Scrollbar for content */
.custom-scrollbar::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}

.custom-scrollbar::-webkit-scrollbar-track {
  background: transparent;
}

.custom-scrollbar::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.1);
  border-radius: 3px;
}

.custom-scrollbar::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.2);
}

/* Mobile Layout Overrides */
@media (max-width: 767px) {
  .dashboard-root {
    height: auto !important;
    min-height: 0;
  }
  
  .resizable-panel {
    height: auto !important;
    min-height: 300px;
  }
  
  .tab-content {
    max-height: 500px;
  }

  .bottom-tabs {
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
    white-space: nowrap;
  }
  .bottom-tab {
    min-height: 44px;
    padding: 10px 14px;
    flex-shrink: 0;
  }
}
</style>
