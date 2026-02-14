<script setup lang="ts">
/**
 * PositionList.vue
 * =================
 * 仓位列表组件 - 显示用户所有仓位及实时盈亏
 * 
 * 功能:
 * - 显示仓位列表和实时盈亏
 * - 修改止盈止损 (弹窗)
 * - 部分平仓 (滑块 + 预计收益)
 */
import { ref, onMounted, onUnmounted, computed, h, watch } from 'vue'
import { NDataTable, NTag, NButton, useMessage, NPopconfirm, NModal, NInputNumber, NSlider, NCard } from 'naive-ui'
import request from '@/utils/request'
import { useWalletStore } from '@/stores/wallet'
import { setPositionTpSl, closePosition as apiClosePosition, calculatePnl } from '@/api/position'

const message = useMessage()
const walletStore = useWalletStore()

// ==================== 类型定义 ====================
interface PositionRisk {
  position_id: number
  symbol: string
  side: string
  size: string
  entry_price: string
  mark_price: string
  leverage: number
  margin: string
  margin_mode: string
  liquidation_price: string | null
  is_dynamic_liq: boolean
  unrealized_pnl: string
  roe_percent: string
  margin_ratio: string
  is_at_risk: boolean
  should_liquidate: boolean
  // 🔥 新增
  stop_loss: string | null
  take_profit: string | null
}

// ==================== 状态 ====================
const positions = ref<PositionRisk[]>([])
const loading = ref(false)
const closingId = ref<number | null>(null)

// 止盈止损弹窗
const showTpSlModal = ref(false)
const tpSlEditing = ref<PositionRisk | null>(null)
const tpSlForm = ref({
  stop_loss: null as number | null,
  take_profit: null as number | null,
})
const tpSlSaving = ref(false)

// 平仓弹窗
const showCloseModal = ref(false)
const closeEditing = ref<PositionRisk | null>(null)
const closePercent = ref(100)  // 0-100
const closeSaving = ref(false)

// ==================== 计算属性 ====================
// 平仓数量
const closeQuantity = computed(() => {
  if (!closeEditing.value) return 0
  const totalSize = parseFloat(closeEditing.value.size)
  return totalSize * (closePercent.value / 100)
})

// 平仓金额 (USDT)
const closeNotional = computed(() => {
  if (!closeEditing.value) return 0
  return closeQuantity.value * parseFloat(closeEditing.value.mark_price)
})

// 预计盈亏
const estimatedPnl = computed(() => {
  if (!closeEditing.value) return 0
  return calculatePnl(
    closeEditing.value.side,
    closeQuantity.value,
    parseFloat(closeEditing.value.entry_price),
    parseFloat(closeEditing.value.mark_price)
  )
})

// ==================== 方法 ====================
// 获取仓位风险数据
async function fetchPositions() {
  try {
    const resp = await request.get('/risk/positions')
    positions.value = resp.data
  } catch (e) {
    console.error('[PositionList] 获取仓位失败:', e)
  }
}

// 打开止盈止损编辑弹窗
function openTpSlModal(position: PositionRisk) {
  tpSlEditing.value = position
  tpSlForm.value = {
    stop_loss: position.stop_loss ? parseFloat(position.stop_loss) : null,
    take_profit: position.take_profit ? parseFloat(position.take_profit) : null,
  }
  showTpSlModal.value = true
}

// 保存止盈止损
async function saveTpSl() {
  if (!tpSlEditing.value) return
  
  tpSlSaving.value = true
  try {
    await setPositionTpSl(tpSlEditing.value.position_id, {
      stop_loss: tpSlForm.value.stop_loss?.toString() ?? null,
      take_profit: tpSlForm.value.take_profit?.toString() ?? null,
    })
    message.success('止盈止损已更新')
    showTpSlModal.value = false
    await fetchPositions()
  } catch (e: any) {
    message.error(e.response?.data?.detail || '保存失败')
  } finally {
    tpSlSaving.value = false
  }
}

// 打开平仓弹窗
function openCloseModal(position: PositionRisk) {
  closeEditing.value = position
  closePercent.value = 100
  showCloseModal.value = true
}

// 执行平仓
async function executeClose() {
  if (!closeEditing.value) return
  
  closeSaving.value = true
  try {
    const params: { close_price: string; quantity?: string } = {
      close_price: closeEditing.value.mark_price,
    }
    
    // 部分平仓
    if (closePercent.value < 100) {
      params.quantity = closeQuantity.value.toString()
    }
    
    const resp = await apiClosePosition(closeEditing.value.position_id, params)
    
    message.success(`平仓成功! 盈亏: ${parseFloat(resp.realized_pnl).toFixed(2)} USDT`)
    showCloseModal.value = false
    
    await fetchPositions()
    await walletStore.fetchBalance()
  } catch (e: any) {
    message.error(e.response?.data?.detail || '平仓失败')
  } finally {
    closeSaving.value = false
  }
}

// 表格列定义
const columns = [
  {
    title: '交易对',
    key: 'symbol',
    width: 100,
    render: (row: PositionRisk) => row.symbol,
  },
  {
    title: '方向',
    key: 'side',
    width: 70,
    render: (row: PositionRisk) => {
      const isLong = row.side === 'long'
      return h(NTag, {
        type: isLong ? 'success' : 'error',
        size: 'small',
      }, { default: () => isLong ? '多' : '空' })
    },
  },
  {
    title: '数量',
    key: 'size',
    width: 100,
    render: (row: PositionRisk) => parseFloat(row.size).toFixed(4),
  },
  {
    title: '开仓价',
    key: 'entry_price',
    width: 100,
    render: (row: PositionRisk) => '$' + parseFloat(row.entry_price).toFixed(2),
  },
  {
    title: '标记价',
    key: 'mark_price',
    width: 100,
    render: (row: PositionRisk) => '$' + parseFloat(row.mark_price).toFixed(2),
  },
  {
    title: '杠杆',
    key: 'leverage',
    width: 60,
    render: (row: PositionRisk) => row.leverage + 'x',
  },
  {
    title: '未实现盈亏',
    key: 'unrealized_pnl',
    width: 120,
    render: (row: PositionRisk) => {
      const pnl = parseFloat(row.unrealized_pnl)
      const roe = parseFloat(row.roe_percent)
      const color = pnl >= 0 ? '#16a34a' : '#dc2626'
      const sign = pnl >= 0 ? '+' : ''
      return h('div', { style: { color } }, [
        h('div', { class: 'font-mono' }, sign + pnl.toFixed(2) + ' USDT'),
        h('div', { class: 'text-xs opacity-70' }, `(${sign}${roe.toFixed(2)}%)`),
      ])
    },
  },
  {
    title: '止盈/止损',
    key: 'tp_sl',
    width: 140,
    render: (row: PositionRisk) => {
      const tp = row.take_profit ? '$' + parseFloat(row.take_profit).toFixed(2) : '-'
      const sl = row.stop_loss ? '$' + parseFloat(row.stop_loss).toFixed(2) : '-'
      return h('div', { 
        class: 'cursor-pointer hover:bg-white/10 rounded px-1 py-0.5 transition',
        onClick: () => openTpSlModal(row)
      }, [
        h('div', { class: 'text-green-400 text-xs' }, `TP: ${tp}`),
        h('div', { class: 'text-red-400 text-xs' }, `SL: ${sl}`),
      ])
    },
  },
  {
    title: '操作',
    key: 'actions',
    width: 100,
    render: (row: PositionRisk) => {
      return h(NButton, {
        size: 'small',
        type: 'error',
        onClick: () => openCloseModal(row),
      }, { default: () => '平仓' })
    },
  },
]

// 定时刷新
let refreshTimer: number | null = null

onMounted(() => {
  fetchPositions()
  refreshTimer = setInterval(fetchPositions, 3000) as unknown as number
})

onUnmounted(() => {
  if (refreshTimer) {
    clearInterval(refreshTimer)
  }
})
</script>

<template>
  <div class="p-4" style="background: #0a0a0a; min-height: 200px;">
    <div class="flex items-center justify-between mb-4">
      <h3 class="text-white text-sm font-medium">当前仓位</h3>
      <NButton 
        size="tiny" 
        quaternary 
        @click="fetchPositions"
        :loading="loading"
      >
        刷新
      </NButton>
    </div>
    
    <NDataTable
      v-if="positions.length > 0"
      :columns="columns"
      :data="positions"
      :row-key="(row: PositionRisk) => row.position_id"
      size="small"
      :bordered="false"
      :single-line="false"
      style="background: transparent;"
      :theme-overrides="{
        thColor: '#18181b',
        tdColor: 'transparent',
        thTextColor: '#9ca3af',
        tdTextColor: '#e5e7eb',
        borderColor: 'rgba(255,255,255,0.05)',
      }"
    />
    
    <div v-else class="text-center py-8 text-gray-500 text-sm">
      暂无仓位
    </div>
    
    <!-- 止盈止损编辑弹窗 -->
    <NModal v-model:show="showTpSlModal" preset="card" style="width: 400px;">
      <template #header>
        <div class="flex items-center gap-2">
          <span>仓位止盈止损</span>
          <NTag size="small" type="info">{{ tpSlEditing?.symbol }}</NTag>
        </div>
      </template>
      
      <div class="space-y-4" v-if="tpSlEditing">
        <!-- 仓位信息 -->
        <div class="grid grid-cols-2 gap-2 text-sm text-gray-400 mb-4">
          <div>开仓价格 (USDT)</div>
          <div class="text-right text-white">${{ parseFloat(tpSlEditing.entry_price).toFixed(2) }}</div>
          <div>标记价格 (USDT)</div>
          <div class="text-right text-white">${{ parseFloat(tpSlEditing.mark_price).toFixed(2) }}</div>
        </div>
        
        <!-- 止盈 -->
        <div>
          <div class="flex justify-between items-center mb-2">
            <span class="text-green-400 text-sm">止盈</span>
            <NButton 
              size="tiny" 
              text 
              type="primary"
              @click="tpSlForm.take_profit = null"
            >取消</NButton>
          </div>
          <NInputNumber
            v-model:value="tpSlForm.take_profit"
            placeholder="止盈价格"
            :precision="2"
            :min="0"
            style="width: 100%"
          />
        </div>
        
        <!-- 止损 -->
        <div>
          <div class="flex justify-between items-center mb-2">
            <span class="text-red-400 text-sm">止损</span>
            <NButton 
              size="tiny" 
              text 
              type="primary"
              @click="tpSlForm.stop_loss = null"
            >取消</NButton>
          </div>
          <NInputNumber
            v-model:value="tpSlForm.stop_loss"
            placeholder="止损价格"
            :precision="2"
            :min="0"
            style="width: 100%"
          />
        </div>
        
        <!-- 确认按钮 -->
        <NButton
          type="primary"
          block
          :loading="tpSlSaving"
          @click="saveTpSl"
        >
          确认
        </NButton>
      </div>
    </NModal>
    
    <!-- 平仓弹窗 -->
    <NModal v-model:show="showCloseModal" preset="card" style="width: 400px;">
      <template #header>
        <div class="flex items-center gap-2">
          <span>平仓</span>
          <NTag size="small" type="info">{{ closeEditing?.symbol }}</NTag>
          <NTag size="small" :type="closeEditing?.side === 'long' ? 'success' : 'error'">
            {{ closeEditing?.leverage }}x
          </NTag>
        </div>
      </template>
      
      <div class="space-y-4" v-if="closeEditing">
        <!-- 仓位信息 -->
        <div class="grid grid-cols-2 gap-2 text-sm text-gray-400">
          <div>开仓价格 (USDT)</div>
          <div class="text-right text-white">${{ parseFloat(closeEditing.entry_price).toFixed(2) }}</div>
          <div>标记价格 (USDT)</div>
          <div class="text-right text-white">${{ parseFloat(closeEditing.mark_price).toFixed(2) }}</div>
        </div>
        
        <div class="border-t border-white/10 my-4"></div>
        
        <!-- 数量选择 -->
        <div>
          <div class="text-sm text-gray-400 mb-2">数量</div>
          <div class="bg-zinc-800 rounded-lg p-3 mb-2">
            <div class="text-white text-lg font-mono">
              {{ closePercent }}% (≈{{ closeQuantity.toFixed(5) }})
            </div>
            <div class="text-xs text-gray-500">USDT</div>
          </div>
          
          <NSlider
            v-model:value="closePercent"
            :min="1"
            :max="100"
            :step="1"
            :marks="{ 25: '25%', 50: '50%', 75: '75%', 100: '100%' }"
          />
        </div>
        
        <div class="border-t border-white/10 my-4"></div>
        
        <!-- 预计结果 -->
        <div class="grid grid-cols-2 gap-2 text-sm">
          <div class="text-gray-400">仓位数量</div>
          <div class="text-right text-white">{{ closeNotional.toFixed(2) }} USDT</div>
          <div class="text-gray-400">预计盈亏</div>
          <div class="text-right font-mono" :class="estimatedPnl >= 0 ? 'text-green-400' : 'text-red-400'">
            {{ estimatedPnl >= 0 ? '+' : '' }}{{ estimatedPnl.toFixed(2) }} USDT
          </div>
        </div>
        
        <!-- 确认按钮 -->
        <NButton
          type="warning"
          block
          :loading="closeSaving"
          @click="executeClose"
        >
          确认
        </NButton>
      </div>
    </NModal>
  </div>
</template>

<style scoped>
:deep(.n-data-table) {
  background: transparent !important;
}
:deep(.n-data-table-th) {
  background: #18181b !important;
}
:deep(.n-data-table-td) {
  background: transparent !important;
}
</style>
