<script setup lang="ts">
/**
 * GridTrading.vue - 网格交易组件 (内联表单)
 * ==========================================
 * 自动高抛低吸的网格机器人
 * 
 * 功能:
 * - 创建网格机器人 (内联表单)
 * - 查看网格列表
 * - 启动/停止网格
 * - 查看网格盈利
 */
import { ref, onMounted, computed, watch } from 'vue'
import { NButton, NInputNumber, NSelect, NTag, NPopconfirm, useMessage } from 'naive-ui'
import request from '@/utils/request'
import { useSymbolStore } from '@/stores/symbol'

const message = useMessage()
const symbolStore = useSymbolStore()

// ==================== 类型定义 ====================
interface GridBot {
  id: number
  name: string
  symbol: string
  grid_type: 'arithmetic' | 'geometric'
  direction: 'long' | 'short' | 'neutral'
  status: 'created' | 'running' | 'stopped' | 'error'
  upper_price: string
  lower_price: string
  grid_count: number
  investment: string
  leverage: number
  grid_interval: string | null
  quantity_per_grid: string | null
  current_level: number
  filled_buy_count: number
  filled_sell_count: number
  total_profit: string
  realized_pnl: string
  profit_rate: string
  created_at: string
  started_at: string | null
}

// ==================== 状态 ====================
const loading = ref(false)
const gridBots = ref<GridBot[]>([])
const showCreateForm = ref(false)
const currentPrice = ref(0)

// 创建表单 - 🔥 默认使用 store 的当前交易对
const form = ref({
  name: '',
  symbol: symbolStore.currentSymbol,
  lower_price: null as number | null,
  upper_price: null as number | null,
  grid_count: 10,
  investment: 100,
  leverage: 5,
  grid_type: 'arithmetic' as 'arithmetic' | 'geometric',
  direction: 'long' as 'long' | 'short' | 'neutral',
})

// ==================== 计算属性 ====================
// 🔥 使用 store 的完整交易对列表
const symbolOptions = computed(() => symbolStore.symbolOptions)

const gridTypeOptions = [
  { label: '等差网格', value: 'arithmetic' },
  { label: '等比网格', value: 'geometric' },
]

const directionOptions = [
  { label: '做多 (低买高卖)', value: 'long' },
  { label: '做空 (高卖低买)', value: 'short' },
  { label: '中性', value: 'neutral' },
]

// 预估每格利润
const estProfitPerGrid = computed(() => {
  if (!form.value.lower_price || !form.value.upper_price || !form.value.grid_count) return '--'
  const range = form.value.upper_price - form.value.lower_price
  const interval = range / form.value.grid_count
  const profitRate = (interval / form.value.lower_price) * 100
  return profitRate.toFixed(2) + '%'
})

// ==================== 方法 ====================

// 获取网格列表
async function fetchGridBots() {
  try {
    const resp = await request.get('/grid/')
    gridBots.value = resp.data
  } catch (e) {
    console.error('[GridTrading] 获取网格失败:', e)
  }
}

// 获取当前价格
async function fetchCurrentPrice() {
  try {
    const resp = await request.get('/market/klines/latest', {
      params: { symbol: form.value.symbol }
    })
    if (resp.data?.close) {
      currentPrice.value = parseFloat(resp.data.close)
      // 自动设置合理的价格区间
      if (!form.value.lower_price) {
        form.value.lower_price = Math.floor(currentPrice.value * 0.9)
      }
      if (!form.value.upper_price) {
        form.value.upper_price = Math.ceil(currentPrice.value * 1.1)
      }
    }
  } catch (e) {
    console.error('[GridTrading] 获取价格失败:', e)
  }
}

// 打开创建表单
function openCreateForm() {
  form.value = {
    name: `${symbolStore.currentSymbol} 网格 #${gridBots.value.length + 1}`,
    symbol: symbolStore.currentSymbol,  // 🔥 使用当前选中的交易对
    lower_price: null,
    upper_price: null,
    grid_count: 10,
    investment: 100,
    leverage: 5,
    grid_type: 'arithmetic',
    direction: 'long',
  }
  fetchCurrentPrice()
  showCreateForm.value = true
}

// 取消创建
function cancelCreate() {
  showCreateForm.value = false
}

// 创建网格
async function createGrid() {
  if (!form.value.name || !form.value.lower_price || !form.value.upper_price) {
    message.warning('请填写完整信息')
    return
  }
  
  loading.value = true
  try {
    const resp = await request.post('/grid/', {
      name: form.value.name,
      symbol: form.value.symbol,
      lower_price: form.value.lower_price.toString(),
      upper_price: form.value.upper_price.toString(),
      grid_count: form.value.grid_count,
      investment: form.value.investment.toString(),
      leverage: form.value.leverage,
      grid_type: form.value.grid_type,
      direction: form.value.direction,
    })
    
    message.success('网格创建成功!')
    showCreateForm.value = false
    await fetchGridBots()
    
  } catch (e: any) {
    const detail = e.response?.data?.detail || '创建失败'
    message.error(detail)
  } finally {
    loading.value = false
  }
}

// 启动网格
async function startGrid(botId: number) {
  loading.value = true
  try {
    // 找到对应的 bot 获取其 symbol
    const bot = gridBots.value.find(b => b.id === botId)
    const symbol = bot?.symbol || symbolStore.currentSymbol  // 🔥 使用 store
    
    // 获取当前价格
    const priceResp = await request.get('/market/klines/latest', {
      params: { symbol }
    })
    const price = parseFloat(priceResp.data?.close || '0')
    
    if (price <= 0) {
      message.error('无法获取当前价格')
      return
    }
    
    await request.post(`/grid/${botId}/start`, {
      current_price: price
    })
    
    message.success('网格已启动!')
    await fetchGridBots()
    
  } catch (e: any) {
    const detail = e.response?.data?.detail || '启动失败'
    message.error(detail)
  } finally {
    loading.value = false
  }
}

// 停止网格
async function stopGrid(botId: number) {
  loading.value = true
  try {
    await request.post(`/grid/${botId}/stop`)
    message.success('网格已停止')
    await fetchGridBots()
  } catch (e: any) {
    const detail = e.response?.data?.detail || '停止失败'
    message.error(detail)
  } finally {
    loading.value = false
  }
}

// 删除网格
async function deleteGrid(botId: number) {
  loading.value = true
  try {
    await request.delete(`/grid/${botId}`)
    message.success('网格已删除')
    await fetchGridBots()
  } catch (e: any) {
    const detail = e.response?.data?.detail || '删除失败'
    message.error(detail)
  } finally {
    loading.value = false
  }
}

// 格式化状态
function formatStatus(status: string) {
  const map: Record<string, { type: 'success' | 'warning' | 'error' | 'info', label: string }> = {
    created: { type: 'info', label: '待启动' },
    running: { type: 'success', label: '运行中' },
    paused: { type: 'warning', label: '已暂停' },
    stopped: { type: 'warning', label: '已停止' },
    completed: { type: 'success', label: '已完成' },
  }
  return map[status] || { type: 'info', label: status }
}

// 初始化
onMounted(() => {
  fetchGridBots()
})
</script>

<template>
  <div class="grid-trading">
    <!-- 头部 -->
    <div class="header">
      <h3>网格交易 <span class="subtitle">自动高抛低吸</span></h3>
      <NButton v-if="!showCreateForm" type="primary" size="small" @click="openCreateForm">
        创建网格
      </NButton>
    </div>
    
    <!-- 内联创建表单 -->
    <div v-if="showCreateForm" class="create-form">
      <div class="form-header">
        <span class="form-title">创建网格机器人</span>
        <button class="close-btn" @click="cancelCreate">取消</button>
      </div>
      
      <div class="form-grid">
        <!-- 左侧配置 -->
        <div class="form-column">
          <div class="form-item">
            <label>名称</label>
            <input v-model="form.name" class="form-input" placeholder="网格名称" />
          </div>
          
          <div class="form-item">
            <label>交易对</label>
            <NSelect v-model:value="form.symbol" :options="symbolOptions" size="small" @update:value="fetchCurrentPrice" />
          </div>
          
          <div class="form-row">
            <div class="form-item half">
              <label>下限价格</label>
              <NInputNumber v-model:value="form.lower_price" :min="0" placeholder="最低价" size="small" />
            </div>
            <div class="form-item half">
              <label>上限价格</label>
              <NInputNumber v-model:value="form.upper_price" :min="0" placeholder="最高价" size="small" />
            </div>
          </div>
          
          <div class="current-price" v-if="currentPrice > 0">
            当前价格: {{ currentPrice.toFixed(2) }}
          </div>
        </div>
        
        <!-- 右侧配置 -->
        <div class="form-column">
          <div class="form-row">
            <div class="form-item half">
              <label>网格数量</label>
              <NInputNumber v-model:value="form.grid_count" :min="2" :max="200" size="small" />
            </div>
            <div class="form-item half">
              <label>杠杆</label>
              <NInputNumber v-model:value="form.leverage" :min="1" :max="125" size="small" />
            </div>
          </div>
          
          <div class="form-item">
            <label>投资金额 (USDT)</label>
            <NInputNumber v-model:value="form.investment" :min="10" size="small" />
          </div>
          
          <div class="form-row">
            <div class="form-item half">
              <label>网格类型</label>
              <NSelect v-model:value="form.grid_type" :options="gridTypeOptions" size="small" />
            </div>
            <div class="form-item half">
              <label>方向</label>
              <NSelect v-model:value="form.direction" :options="directionOptions" size="small" />
            </div>
          </div>
        </div>
      </div>
      
      <!-- 预估利润 -->
      <div class="estimate-bar">
        <span>预估每格利润: <strong>{{ estProfitPerGrid }}</strong></span>
        <NButton type="primary" :loading="loading" @click="createGrid">
          创建网格
        </NButton>
      </div>
    </div>
    
    <!-- 网格列表 -->
    <div class="grid-list">
      <div v-if="gridBots.length === 0 && !showCreateForm" class="empty">
        <p>暂无网格机器人</p>
        <p class="hint">创建一个网格，让机器人自动帮你高抛低吸</p>
      </div>
      
      <div v-for="bot in gridBots" :key="bot.id" class="grid-card">
        <div class="card-header">
          <span class="name">{{ bot.name }}</span>
          <NTag :type="formatStatus(bot.status).type" size="small">
            {{ formatStatus(bot.status).label }}
          </NTag>
        </div>
        
        <div class="card-body">
          <div class="stat-grid">
            <div class="stat-item">
              <span class="label">交易对</span>
              <span class="value">{{ bot.symbol }}</span>
            </div>
            <div class="stat-item">
              <span class="label">价格区间</span>
              <span class="value">{{ bot.lower_price }} - {{ bot.upper_price }}</span>
            </div>
            <div class="stat-item">
              <span class="label">网格数</span>
              <span class="value">{{ bot.grid_count }}</span>
            </div>
            <div class="stat-item">
              <span class="label">投资</span>
              <span class="value">{{ bot.investment }} USDT</span>
            </div>
            <div class="stat-item">
              <span class="label">成交</span>
              <span class="value">
                <span class="green">买{{ bot.filled_buy_count }}</span> / 
                <span class="red">卖{{ bot.filled_sell_count }}</span>
              </span>
            </div>
            <div class="stat-item highlight">
              <span class="label">总收益</span>
              <span :class="['value', parseFloat(bot.total_profit) >= 0 ? 'green' : 'red']">
                {{ bot.total_profit }} ({{ bot.profit_rate }}%)
              </span>
            </div>
          </div>
        </div>
        
        <div class="card-actions">
          <template v-if="bot.status === 'created'">
            <NButton size="small" type="success" @click="startGrid(bot.id)" :loading="loading">
              启动
            </NButton>
            <NPopconfirm @positive-click="deleteGrid(bot.id)">
              <template #trigger>
                <NButton size="small" type="error" :loading="loading" style="margin-left: 8px;">
                  删除
                </NButton>
              </template>
              确定要删除这个网格吗? 此操作不可撤销!
            </NPopconfirm>
          </template>
          <template v-else-if="bot.status === 'running'">
            <NPopconfirm @positive-click="stopGrid(bot.id)">
              <template #trigger>
                <NButton size="small" type="warning" :loading="loading">
                  停止
                </NButton>
              </template>
              确定要停止这个网格吗?
            </NPopconfirm>
          </template>
          <template v-else>
            <NButton size="small" type="primary" @click="startGrid(bot.id)" :loading="loading">
              重启
            </NButton>
            <NPopconfirm @positive-click="deleteGrid(bot.id)">
              <template #trigger>
                <NButton size="small" type="error" :loading="loading" style="margin-left: 8px;">
                  删除
                </NButton>
              </template>
              确定要删除这个网格吗? 此操作不可撤销!
            </NPopconfirm>
          </template>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.grid-trading {
  padding: 16px;
  background: #0a0a0a;
  min-height: 200px;
}

.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.header h3 {
  font-size: 14px;
  font-weight: 500;
  color: #f5f5f5;
  margin: 0;
}

.subtitle {
  font-size: 12px;
  color: #6b7280;
  font-weight: normal;
  margin-left: 8px;
}

/* 创建表单 */
.create-form {
  background: #18181b;
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 8px;
  padding: 16px;
  margin-bottom: 16px;
}

.form-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.form-title {
  font-weight: 500;
  color: #f5f5f5;
}

.close-btn {
  background: none;
  border: none;
  color: #6b7280;
  cursor: pointer;
  font-size: 12px;
}

.close-btn:hover {
  color: #f5f5f5;
}

.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.form-column {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.form-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.form-item label {
  font-size: 11px;
  color: #9ca3af;
}

.form-input {
  background: #0e0e10;
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 4px;
  padding: 6px 10px;
  color: #f5f5f5;
  font-size: 12px;
  outline: none;
}

.form-row {
  display: flex;
  gap: 10px;
}

.form-item.half {
  flex: 1;
}

.current-price {
  font-size: 11px;
  color: #f97316;
  text-align: center;
  padding: 4px;
  background: rgba(249, 115, 22, 0.1);
  border-radius: 4px;
}

.estimate-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid rgba(255,255,255,0.05);
}

.estimate-bar span {
  font-size: 12px;
  color: #9ca3af;
}

.estimate-bar strong {
  color: #22c55e;
}

/* 网格列表 */
.grid-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.empty {
  text-align: center;
  padding: 40px;
  color: #6b7280;
}

.empty p {
  margin: 4px 0;
}

.empty .hint {
  font-size: 12px;
}

.grid-card {
  background: #18181b;
  border: 1px solid rgba(255,255,255,0.05);
  border-radius: 8px;
  padding: 12px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

.card-header .name {
  font-weight: 500;
  color: #f5f5f5;
}

.card-body {
  margin-bottom: 10px;
}

.stat-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
}

.stat-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.stat-item .label {
  color: #6b7280;
  font-size: 10px;
}

.stat-item .value {
  color: #e5e7eb;
  font-size: 11px;
}

.stat-item.highlight {
  grid-column: span 3;
  flex-direction: row;
  justify-content: space-between;
  padding-top: 8px;
  border-top: 1px solid rgba(255,255,255,0.05);
}

.green { color: #22c55e; }
.red { color: #ef4444; }

.card-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>
