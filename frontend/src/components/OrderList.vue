<script setup lang="ts">
/**
 * OrderList.vue
 * ==============
 * 订单列表组件 - 显示用户挂单和历史订单
 */
import { ref, computed, h } from 'vue'
import { NDataTable, NTag, NButton, NTabs, NTabPane, useMessage, NPopconfirm } from 'naive-ui'
import { listOrders, cancelOrder as apiCancelOrder, type OrderResponse } from '@/api/order'

const message = useMessage()

// 使用统一的 OrderResponse 类型
type Order = OrderResponse

const orders = ref<Order[]>([])
const loading = ref(false)
const cancelingId = ref<number | null>(null)
const activeTab = ref<'open' | 'all'>('open')

// 获取订单列表
async function fetchOrders() {
  loading.value = true
  try {
    orders.value = await listOrders()
  } catch (e) {
    console.error('[OrderList] 获取订单失败:', e)
  } finally {
    loading.value = false
  }
}

// 取消订单
async function cancelOrder(orderId: number) {
  cancelingId.value = orderId
  
  try {
    await apiCancelOrder(orderId)
    message.success('订单已取消')
    await fetchOrders()
  } catch (e: any) {
    const detail = e.response?.data?.detail || '取消失败'
    message.error(detail)
  } finally {
    cancelingId.value = null
  }
}

// 过滤开放订单
const openOrders = computed(() => {
  return orders.value.filter(o => ['pending', 'open', 'partially_filled'].includes(o.status))
})

const displayOrders = computed(() => {
  return activeTab.value === 'open' ? openOrders.value : orders.value
})

// 状态颜色映射
function getStatusType(status: string) {
  switch (status) {
    case 'filled': return 'success'
    case 'cancelled': return 'default'
    case 'pending':
    case 'open': return 'info'
    case 'partially_filled': return 'warning'
    case 'failed': return 'error'
    default: return 'default'
  }
}

// 状态中文
function getStatusText(status: string) {
  const map: Record<string, string> = {
    pending: '待处理',
    open: '挂单中',
    partially_filled: '部分成交',
    filled: '已成交',
    cancelled: '已取消',
    failed: '失败',
  }
  return map[status] || status
}

// 订单类型中文
function getOrderTypeText(type: string) {
  const map: Record<string, string> = {
    market: '市价',
    limit: '限价',
    stop_market: '止损市价',
    stop_limit: '止损限价',
    take_profit_market: '止盈市价',
    take_profit_limit: '止盈限价',
  }
  return map[type] || type
}

// 表格列
const columns = [
  {
    title: '时间',
    key: 'created_at',
    width: 150,
    render: (row: Order) => new Date(row.created_at).toLocaleString('zh-CN'),
  },
  {
    title: '交易对',
    key: 'symbol',
    width: 100,
  },
  {
    title: '方向',
    key: 'side',
    width: 70,
    render: (row: Order) => {
      const isBuy = row.side === 'buy'
      return h(NTag, {
        type: isBuy ? 'success' : 'error',
        size: 'small',
      }, { default: () => isBuy ? '买入' : '卖出' })
    },
  },
  {
    title: '类型',
    key: 'order_type',
    width: 80,
    render: (row: Order) => getOrderTypeText(row.order_type),
  },
  {
    title: '价格',
    key: 'price',
    width: 100,
    render: (row: Order) => {
      if (row.order_type === 'market') return '市价'
      return row.price ? '$' + parseFloat(row.price).toFixed(2) : '-'
    },
  },
  {
    title: '数量',
    key: 'quantity',
    width: 100,
    render: (row: Order) => parseFloat(row.quantity).toFixed(4),
  },
  {
    title: '成交',
    key: 'filled_quantity',
    width: 100,
    render: (row: Order) => parseFloat(row.filled_quantity).toFixed(4),
  },
  {
    title: '杠杆',
    key: 'leverage',
    width: 60,
    render: (row: Order) => row.leverage + 'x',
  },
  {
    title: '状态',
    key: 'status',
    width: 100,
    render: (row: Order) => h(NTag, {
      type: getStatusType(row.status),
      size: 'small',
    }, { default: () => getStatusText(row.status) })
  },
  {
    title: '操作',
    key: 'actions',
    width: 80,
    render: (row: Order) => {
      if (!['pending', 'open', 'partially_filled'].includes(row.status)) {
        return '-'
      }
      return h(NPopconfirm, {
        onPositiveClick: () => cancelOrder(row.id),
      }, {
        trigger: () => h(NButton, {
          size: 'small',
          type: 'warning',
          loading: cancelingId.value === row.id,
        }, { default: () => '取消' }),
        default: () => '确定要取消这个订单吗?',
      })
    },
  },
]

// 智能轮询: 5秒间隔，标签页后台自动暂停
import { useVisibilityPolling } from '@/composables/useVisibilityPolling'
useVisibilityPolling(fetchOrders, 5000)

// 辅助函数: 安全格式化数字
function formatNumber(val: string | number | null | undefined, decimals: number = 2): string {
  if (val === null || val === undefined || val === '') return '--'
  const num = typeof val === 'string' ? parseFloat(val) : val
  if (isNaN(num)) return '--'
  return num.toFixed(decimals)
}
</script>

<template>
  <div class="p-4" style="background: transparent; min-height: 200px;">
    <div class="flex items-center justify-between mb-4">
      <NTabs v-model:value="activeTab" type="segment" size="small">
        <NTabPane name="open" tab="挂单" />
        <NTabPane name="all" tab="全部" />
      </NTabs>
      <NButton 
        size="tiny" 
        quaternary 
        @click="fetchOrders"
        :loading="loading"
      >
        刷新
      </NButton>
    </div>
    
    <!-- Desktop View -->
    <div class="hidden md:block">
      <NDataTable
        v-if="displayOrders.length > 0"
        :columns="columns"
        :data="displayOrders"
        :row-key="(row: Order) => row.id"
        size="small"
        :bordered="false"
        :theme-overrides="{
          thColor: 'rgba(255,255,255,0.02)',
          tdColor: 'transparent',
          thTextColor: '#9ca3af',
          tdTextColor: '#e5e7eb',
          borderColor: 'rgba(255,255,255,0.05)',
        }"
      />
    </div>

    <!-- Mobile View -->
    <div class="md:hidden space-y-3" v-if="displayOrders.length > 0">
      <div 
        v-for="order in displayOrders" 
        :key="order.id" 
        class="glass-panel p-3 rounded-xl border border-white/5"
      >
        <!-- Header -->
        <div class="flex justify-between items-center mb-2">
          <div class="flex items-center gap-2">
            <span class="font-bold text-white">{{ order.symbol }}</span>
            <NTag size="small" :type="order.side === 'buy' ? 'success' : 'error'">
              {{ order.side === 'buy' ? '买入' : '卖出' }}
            </NTag>
            <span class="text-xs text-gray-400">{{ order.leverage }}x</span>
          </div>
          <div class="text-xs text-gray-500">
            {{ new Date(order.created_at).toLocaleTimeString() }}
          </div>
        </div>
        
        <!-- Details -->
        <div class="grid grid-cols-2 gap-y-1 text-sm mb-3">
          <div class="text-gray-500">类型</div>
          <div class="text-right text-gray-300">{{ getOrderTypeText(order.order_type) }}</div>
          
          <div class="text-gray-500">价格</div>
          <div class="text-right font-mono">{{ order.price ? formatNumber(order.price, 2) : '市价' }}</div>
          
          <div class="text-gray-500">数量</div>
          <div class="text-right font-mono">{{ formatNumber(order.quantity, 4) }}</div>
          
          <div class="text-gray-500">成交</div>
          <div class="text-right font-mono">{{ formatNumber(order.filled_quantity, 4) }}</div>
        </div>
        
        <!-- Footer -->
        <div class="flex justify-between items-center pt-2 border-t border-white/5">
          <NTag size="small" :type="getStatusType(order.status)" :bordered="false">
            {{ getStatusText(order.status) }}
          </NTag>
          
          <NButton 
            v-if="['pending', 'open', 'partially_filled'].includes(order.status)"
            size="tiny" 
            type="warning" 
            secondary
            :loading="cancelingId === order.id"
            @click="cancelOrder(order.id)"
          >
            取消
          </NButton>
        </div>
      </div>
    </div>
    
    <div v-else class="text-center py-8 text-gray-500 text-sm">
      暂无{{ activeTab === 'open' ? '挂单' : '订单' }}
    </div>
  </div>
</template>

<style scoped>
:deep(.n-data-table) {
  background: transparent !important;
}
:deep(.n-tabs) {
  --n-tab-text-color: #6b7280;
  --n-tab-text-color-active: #a855f7;
  --n-tab-color-segment: #18181b;
}
</style>
