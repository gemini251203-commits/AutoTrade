<script setup lang="ts">
/**
 * TradePanel.vue - 专业交易面板
 * ================================
 * 
 * 功能:
 * - 全仓/逐仓保证金模式选择
 * - 杠杆选择器 (弹窗)
 * - 市价/限价订单
 * - 价格输入 (BBO 一键填入最新价)
 * - 数量输入 (USDT/BTC 切换)
 * - 止盈止损设置
 * - 预估强平价格
 * 
 * 币安规则: 同一交易对不能同时持有多单和空单
 */
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { NModal, NCheckbox, NSlider, useMessage } from 'naive-ui'
import request from '@/utils/request'
import { useWalletStore } from '@/stores/wallet'
import { useSymbolStore } from '@/stores/symbol'
import { previewTpSl, type TpSlPreviewResponse } from '@/api/order'
import { useWebSocket } from '@/composables/useWebSocket'


const message = useMessage()
const walletStore = useWalletStore()
const symbolStore = useSymbolStore()
const { getPrice, isConnected: wsConnected } = useWebSocket()

// ==================== 基础状态 ====================
// 🔥 从 store 获取当前交易对
const symbol = computed(() => symbolStore.currentSymbol)
const baseAsset = computed(() => symbolStore.baseAsset)  // BTC, ETH 等
const currentPrice = ref(0)
const loading = ref(false)

// ==================== 保证金模式 ====================
const marginMode = ref<'cross' | 'isolated'>('cross')

// ==================== 杠杆 ====================
const leverage = ref(20)
const showLeverageModal = ref(false)
const tempLeverage = ref(20)

// ==================== 订单类型 ====================
type OrderTypeTab = 'market' | 'limit'
const orderTypeTab = ref<OrderTypeTab>('limit')

// ==================== 价格和仓位 ====================
const price = ref<number | null>(null)
// 🔥 改为仓位大小 (USDT 名义价值)
const notional = ref<number | null>(null)
const sliderValue = ref(0)

// ==================== 止盈止损 ====================
const enableTpSl = ref(false)
const takeProfit = ref<number | null>(null)
const stopLoss = ref<number | null>(null)

// ==================== 止盈止损预览 ====================
const tpSlPreview = ref<TpSlPreviewResponse | null>(null)
const tpSlPreviewLoading = ref(false)

// ==================== 其他选项 ====================
const reduceOnly = ref(false)

// ==================== 现有仓位检查 ====================
const existingPosition = ref<{side: string, size: string} | null>(null)

// ==================== 计算属性 ====================

// 最大名义价值 = 可用保证金 × 杠杆
const maxNotional = computed(() => {
  return walletStore.available * leverage.value
})

// 实际开仓数量 (BTC) = 仓位大小 / 价格
const actualQuantity = computed(() => {
  if (!notional.value) return 0
  const p = orderTypeTab.value === 'market' ? currentPrice.value : (price.value || currentPrice.value)
  if (p <= 0) return 0
  return notional.value / p
})

// BTC 数量显示
const btcQuantityDisplay = computed(() => {
  const qty = actualQuantity.value
  if (qty <= 0) return '0'
  return qty.toFixed(5)
})

// 预估强平价格
const estLiqPriceLong = computed(() => {
  const p = orderTypeTab.value === 'market' ? currentPrice.value : (price.value || 0)
  if (!p || !leverage.value) return '--'
  const liq = p * (1 - 1/leverage.value + 0.004)
  return liq.toFixed(2)
})

const estLiqPriceShort = computed(() => {
  const p = orderTypeTab.value === 'market' ? currentPrice.value : (price.value || 0)
  if (!p || !leverage.value) return '--'
  const liq = p * (1 + 1/leverage.value - 0.004)
  return liq.toFixed(2)
})

// 保证金计算 = 仓位大小 / 杠杆
const marginRequired = computed(() => {
  if (!notional.value || !leverage.value) return '0.00'
  const margin = notional.value / leverage.value
  return margin.toFixed(2)
})

// 强平价格显示 (始终返回对象以保证类型安全)
const liquidationPriceDisplay = computed(() => {
  const p = orderTypeTab.value === 'market' ? currentPrice.value : (price.value || 0)
  if (!p || !leverage.value) {
    return { long: '--', short: '--' }
  }
  // 做多强平 (简化公式)
  const liqLong = p * (1 - 1/leverage.value + 0.004)
  const liqShort = p * (1 + 1/leverage.value - 0.004)
  return { long: liqLong.toFixed(2), short: liqShort.toFixed(2) }
})

// ==================== 方法 ====================

// 获取最新价格 (实时行情)
async function fetchLatestPrice() {
  try {
    const resp = await request.get(`/market/ticker/${symbol.value}`)
    if (resp.data?.price) {
      currentPrice.value = resp.data.price
      if (!price.value) {
        price.value = currentPrice.value
      }
    }
  } catch (e) {
    console.error('[TradePanel] 获取价格失败:', e)
  }
}

// 获取现有仓位
async function fetchExistingPosition() {
  try {
    // 使用正确的参数名 status_filter (与后端一致)
    const resp = await request.get('/position/', { params: { status_filter: 'open' } })
    const positions = resp.data || []
    const symbolPosition = positions.find((p: any) => p.symbol === symbol.value)
    if (symbolPosition) {
      existingPosition.value = {
        side: symbolPosition.side,
        size: symbolPosition.size,
      }
    } else {
      existingPosition.value = null
    }
  } catch (e) {
    console.error('[TradePanel] 获取仓位失败:', e)
    existingPosition.value = null  // 失败时清空
  }
}

// BBO - 填入最优价格 (最新成交价)
async function fillBBO() {
  try {
    const resp = await request.get(`/market/ticker/${symbol.value}`)
    if (resp.data?.price) {
      const latestPrice = resp.data.price
      currentPrice.value = latestPrice
      price.value = latestPrice
      message.success('已填入最新价格')
    }
  } catch (e) {
    message.error('获取最新价失败')
  }
}

// 杠杆确认
function confirmLeverage() {
  leverage.value = tempLeverage.value
  showLeverageModal.value = false
}

// 打开杠杆弹窗
function openLeverageModal() {
  tempLeverage.value = leverage.value
  showLeverageModal.value = true
}

// 滑块变化 -> 更新 notional
function onSliderChange(value: number) {
  sliderValue.value = value
  const maxVal = maxNotional.value
  notional.value = parseFloat((maxVal * value / 100).toFixed(2))
}

// notional 输入变化 -> 更新滑块
function onNotionalInput() {
  const maxVal = maxNotional.value
  if (maxVal > 0 && notional.value) {
    const pct = Math.min(100, (notional.value / maxVal) * 100)
    sliderValue.value = Math.round(pct)
  } else {
    sliderValue.value = 0
  }
}

// 滑块格式化
function formatSliderTooltip(value: number) {
  return `${value}%`
}

// 监听 leverage 变化，重新计算滑块位置
watch(leverage, () => {
  onNotionalInput()
})

// 开仓
async function openPosition(side: 'long' | 'short') {
  if (loading.value) return
  
  // 注意: 后端已实现净仓位模式
  // - 反向开仓 = 减仓/平仓
  // - 无需前端阻止
  
  const qty = actualQuantity.value
  if (!qty || qty <= 0) {
    message.warning('请输入数量')
    return
  }
  
  const entryPrice = orderTypeTab.value === 'market' 
    ? currentPrice.value 
    : (price.value || currentPrice.value)
  
  if (entryPrice <= 0) {
    message.warning('无法获取价格')
    return
  }
  
  loading.value = true
  
  try {
    const payload = {
      symbol: symbol.value,
      side: side,
      quantity: qty.toFixed(5),
      entry_price: entryPrice.toString(),
      leverage: leverage.value,
      margin_mode: marginMode.value,
      reduce_only: reduceOnly.value,  // 只减仓
      take_profit: enableTpSl.value && takeProfit.value ? takeProfit.value.toString() : null,
      stop_loss: enableTpSl.value && stopLoss.value ? stopLoss.value.toString() : null,
    }
    
    const resp = await request.post('/position/open', payload)
    message.success(`${side === 'long' ? '开多' : '开空'} 成功!`)
    
    await walletStore.fetchBalance()
    await fetchExistingPosition()
    
    // 清空输入
    notional.value = null
    sliderValue.value = 0
    
  } catch (e: any) {
    console.error('[TradePanel] 开仓失败:', e)
    const detail = e.response?.data?.detail || '开仓失败'
    
    // 409 Conflict = 仓位冲突
    if (e.response?.status === 409) {
      message.error('仓位冲突: 请先平掉现有仓位')
    } else {
      message.error(detail)
    }
  } finally {
    loading.value = false
  }
}

// 获取止盈止损预览
async function fetchTpSlPreview(side: 'long' | 'short') {
  if (!enableTpSl.value) {
    tpSlPreview.value = null
    return
  }
  
  const qty = actualQuantity.value
  const entryP = orderTypeTab.value === 'market' ? currentPrice.value : (price.value || currentPrice.value)
  const entryPrice = entryP
  
  if (!qty || qty <= 0 || !entryPrice || entryPrice <= 0) {
    tpSlPreview.value = null
    return
  }
  
  // 至少有一个 TP 或 SL
  if (!takeProfit.value && !stopLoss.value) {
    tpSlPreview.value = null
    return
  }
  
  tpSlPreviewLoading.value = true
  
  try {
    const result = await previewTpSl({
      symbol: symbol.value,
      side: side,
      quantity: qty.toFixed(5),
      entry_price: entryPrice.toString(),
      take_profit: takeProfit.value ? takeProfit.value.toString() : undefined,
      stop_loss: stopLoss.value ? stopLoss.value.toString() : undefined,
      leverage: leverage.value,
    })
    
    tpSlPreview.value = result
  } catch (e) {
    console.error('[TradePanel] TP/SL 预览失败:', e)
    tpSlPreview.value = null
  } finally {
    tpSlPreviewLoading.value = false
  }
}

// 监听止盈止损变化
let tpSlDebounceTimer: ReturnType<typeof setTimeout> | null = null

watch(
  [enableTpSl, takeProfit, stopLoss, notional, price, currentPrice, leverage],
  () => {
    if (tpSlDebounceTimer) {
      clearTimeout(tpSlDebounceTimer)
    }
    tpSlDebounceTimer = setTimeout(() => {
      // 默认按做多方向预览
      fetchTpSlPreview('long')
    }, 300)
  }
)

// 🔥 监听交易对变化，重新获取价格和仓位
watch(() => symbolStore.currentSymbol, async (newSymbol, oldSymbol) => {
  if (newSymbol !== oldSymbol) {

    // 重置价格
    currentPrice.value = 0
    price.value = null
    // 重新获取数据
    await fetchLatestPrice()
    await fetchExistingPosition()
  }
})

// 初始化
let priceCheckInterval: ReturnType<typeof setInterval> | null = null
let positionInterval: ReturnType<typeof setInterval> | null = null

onMounted(async () => {
  await fetchLatestPrice()
  await fetchExistingPosition()
  
  // 🔥 WebSocket 实时价格更新 (替代 setInterval 1s 轮询)
  // 每 500ms 检查 WS 价格，比 HTTP 轮询节省大量请求
  priceCheckInterval = setInterval(() => {
    if (wsConnected.value) {
      const wsPrice = getPrice(symbol.value)
      if (wsPrice > 0) {
        currentPrice.value = wsPrice
        if (!price.value) {
          price.value = wsPrice
        }
      }
    }
  }, 500)
  
  positionInterval = setInterval(fetchExistingPosition, 5000)
})

onUnmounted(() => {
  if (priceCheckInterval) clearInterval(priceCheckInterval)
  if (positionInterval) clearInterval(positionInterval)
})
</script>

<template>
  <div class="trade-panel">
    <!-- 顶部: 全仓 + 杠杆 -->
    <div class="top-bar">
      <div class="margin-mode-label">
        全仓
      </div>
      <button 
        class="leverage-btn"
        @click="openLeverageModal"
      >
        {{ leverage }}x
      </button>
    </div>
    
    <!-- 订单类型 Tabs -->
    <div class="order-tabs">
      <button 
        :class="['tab', orderTypeTab === 'market' ? 'active' : '']"
        @click="orderTypeTab = 'market'"
      >
        市价
      </button>
      <button 
        :class="['tab', orderTypeTab === 'limit' ? 'active orange' : '']"
        @click="orderTypeTab = 'limit'"
      >
        限价
      </button>
    </div>
    
    <!-- 可用余额 -->
    <div class="available">
      可用 <span class="value">{{ walletStore.formattedBalance }} USDT</span>
    </div>
    
    <!-- 价格输入 -->
    <div v-if="orderTypeTab === 'limit'" class="input-group">
      <input 
        v-model.number="price"
        type="number"
        placeholder="价格"
        class="input"
      />
      <span class="unit">USDT</span>
      <button class="bbo-btn" @click="fillBBO">BBO</button>
    </div>
    
    <!-- 市价单显示 -->
    <div v-else class="market-price-display">
      <span class="label">市场价格</span>
      <span class="price">{{ currentPrice.toFixed(2) }}</span>
    </div>
    
    <!-- 仓位大小输入 (USDT 名义价值) -->
    <div class="input-group">
      <input 
        v-model.number="notional"
        type="number"
        placeholder="仓位大小"
        class="input"
        @input="onNotionalInput"
      />
      <span class="unit">USDT</span>
    </div>
    <!-- BTC 数量显示 -->
    <div class="btc-display" v-if="notional && notional > 0">
      ≈ {{ btcQuantityDisplay }} {{ baseAsset }}
    </div>
    
    <!-- 滑块 -->
    <div class="slider-wrapper">
      <NSlider 
        v-model:value="sliderValue"
        :min="0"
        :max="100"
        :step="1"
        :format-tooltip="formatSliderTooltip"
        @update:value="onSliderChange"
      />
    </div>
    
    <!-- 信息行: 强平价/最大仓位/保证金 -->
    <div class="info-rows">
      <div class="info-row">
        <span class="info-label">强平价格</span>
        <span class="info-value">
          多: {{ liquidationPriceDisplay.long }} / 空: {{ liquidationPriceDisplay.short }}
        </span>
      </div>
      <div class="info-row">
        <span class="info-label">最大仓位</span>
        <span class="info-value highlight">{{ maxNotional.toFixed(2) }} USDT</span>
      </div>
      <div class="info-row">
        <span class="info-label">保证金</span>
        <span class="info-value">{{ marginRequired }} USDT</span>
      </div>
    </div>
    
    <!-- 止盈止损 -->
    <div class="tp-sl-section">
      <NCheckbox v-model:checked="enableTpSl" size="small">
        <span class="tp-sl-label">止盈/止损</span>
      </NCheckbox>
      
      <template v-if="enableTpSl">
        <div class="tp-sl-inputs">
          <div class="input-group small">
            <span class="prefix">止盈</span>
            <input 
              v-model.number="takeProfit"
              type="number"
              placeholder="价格"
              class="input"
            />
          </div>
          <div class="input-group small">
            <span class="prefix">止损</span>
            <input 
              v-model.number="stopLoss"
              type="number"
              placeholder="价格"
              class="input"
            />
          </div>
        </div>
        
        <!-- 止盈止损预览 -->
        <div v-if="tpSlPreview" class="tp-sl-preview">
          <div class="preview-row" v-if="tpSlPreview.take_profit_pnl !== 0">
            <span class="preview-label">预计止盈</span>
            <span :class="['preview-value', 'profit']">
              +{{ tpSlPreview.take_profit_pnl.toFixed(2) }} USDT
              <span class="pct">(+{{ tpSlPreview.take_profit_pct.toFixed(1) }}%)</span>
            </span>
          </div>
          <div class="preview-row" v-if="tpSlPreview.stop_loss_pnl !== 0">
            <span class="preview-label">预计止损</span>
            <span :class="['preview-value', 'loss']">
              {{ tpSlPreview.stop_loss_pnl.toFixed(2) }} USDT
              <span class="pct">({{ tpSlPreview.stop_loss_pct.toFixed(1) }}%)</span>
            </span>
          </div>
          <div class="preview-row" v-if="tpSlPreview.risk_reward_ratio > 0">
            <span class="preview-label">风险回报比</span>
            <span class="preview-value ratio">1 : {{ tpSlPreview.risk_reward_ratio.toFixed(2) }}</span>
          </div>
        </div>
      </template>
    </div>
    
    <!-- 只减仓选项 -->
    <div class="options">
      <NCheckbox v-model:checked="reduceOnly" size="small">
        <span class="option-label">只减仓</span>
      </NCheckbox>
    </div>
    
    <!-- 下单按钮 -->
    <div class="order-buttons">
      <button 
        class="order-btn long"
        :disabled="loading || (existingPosition?.side === 'short')"
        @click="openPosition('long')"
      >
        {{ loading ? '处理中...' : '开多' }}
      </button>
      <button 
        class="order-btn short"
        :disabled="loading || (existingPosition?.side === 'long')"
        @click="openPosition('short')"
      >
        {{ loading ? '处理中...' : '开空' }}
      </button>
    </div>
    
    <!-- 预估信息 -->
    <div class="estimates">
      <div class="est-row">
        <span class="est-label">预估强平价格</span>
        <div class="est-values">
          <span class="est-value green">多: {{ estLiqPriceLong }}</span>
          <span class="est-value red">空: {{ estLiqPriceShort }}</span>
        </div>
      </div>
      <div class="est-row">
        <span class="est-label">保证金</span>
        <span class="est-value">{{ marginRequired }} USDT</span>
      </div>
      <div class="est-row" v-if="actualQuantity > 0">
        <span class="est-label">开仓数量</span>
        <span class="est-value">{{ actualQuantity.toFixed(5) }} {{ baseAsset }}</span>
      </div>
    </div>
    
    <!-- 杠杆选择弹窗 -->
    <NModal v-model:show="showLeverageModal" preset="card" style="width: 320px;">
      <template #header>
        <span>{{ symbol }} 调整杠杆</span>
      </template>
      <div class="leverage-modal">
        <div class="leverage-input-row">
          <button class="lev-btn" @click="tempLeverage = Math.max(1, tempLeverage - 1)">-</button>
          <input v-model.number="tempLeverage" type="number" class="lev-input" min="1" max="125" />
          <button class="lev-btn" @click="tempLeverage = Math.min(125, tempLeverage + 1)">+</button>
        </div>
        <div class="leverage-presets">
          <button v-for="lev in [1, 5, 10, 20, 50, 100]" :key="lev"
            :class="['preset', tempLeverage === lev ? 'active' : '']"
            @click="tempLeverage = lev"
          >
            {{ lev }}x
          </button>
        </div>
        <button class="confirm-btn" @click="confirmLeverage">确认</button>
      </div>
    </NModal>
  </div>
</template>

<style scoped>
.trade-panel {
  padding: 12px;
  background: #0e0e10;
  height: 100%;
  display: flex;
  flex-direction: column;
  font-size: 12px;
  color: #9ca3af;
}

/* 顶部栏 */
.top-bar {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}

.margin-mode-label {
  flex: 2;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #a855f7, #ec4899);
  border-radius: 4px;
  color: white;
  font-weight: 500;
  font-size: 12px;
  padding: 8px 12px;
}

.leverage-btn {
  flex: 1;
  padding: 8px 12px;
  background: #1e1e22;
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 4px;
  color: #f5f5f5;
  font-weight: 600;
  cursor: pointer;
}

.leverage-btn:hover {
  background: #2a2a30;
}

/* 现有仓位提示 */
.existing-position {
  padding: 6px 10px;
  background: rgba(249, 115, 22, 0.1);
  border: 1px solid rgba(249, 115, 22, 0.2);
  border-radius: 4px;
  color: #f97316;
  font-size: 11px;
  margin-bottom: 10px;
  text-align: center;
}

/* 订单类型 Tabs */
.order-tabs {
  display: flex;
  gap: 16px;
  margin-bottom: 12px;
  border-bottom: 1px solid rgba(255,255,255,0.05);
  padding-bottom: 8px;
}

.tab {
  background: none;
  border: none;
  color: #6b7280;
  cursor: pointer;
  padding: 4px 0;
  font-size: 13px;
}

.tab.active {
  color: #f5f5f5;
}

.tab.orange {
  color: #f97316;
}

/* 可用余额 */
.available {
  margin-bottom: 8px;
  font-size: 12px;
}

.available .value {
  color: #22c55e;
  margin-left: 4px;
}

/* 市价显示 */
.market-price-display {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: #18181b;
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 4px;
  padding: 10px 12px;
  margin-bottom: 8px;
}

.market-price-display .label {
  color: #6b7280;
}

.market-price-display .price {
  color: #f5f5f5;
  font-weight: 600;
}

/* 输入框组 */
.input-group {
  display: flex;
  align-items: center;
  background: #18181b;
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 4px;
  margin-bottom: 8px;
  padding: 0 8px;
}

.input-group .input {
  flex: 1;
  background: transparent;
  border: none;
  color: #f5f5f5;
  padding: 10px 0;
  font-size: 14px;
  outline: none;
}

.input-group .unit {
  color: #6b7280;
  font-size: 12px;
}

.unit-btn {
  background: #2a2a30;
  border: none;
  color: #9ca3af;
  padding: 4px 8px;
  border-radius: 3px;
  cursor: pointer;
  font-size: 12px;
}

.unit-btn:hover {
  background: #3a3a40;
  color: #f5f5f5;
}

.bbo-btn {
  background: #2a2a30;
  border: none;
  color: #9ca3af;
  padding: 4px 8px;
  border-radius: 3px;
  cursor: pointer;
  margin-left: 8px;
}

.bbo-btn:hover {
  background: #3a3a40;
}

.input-group.small {
  margin-bottom: 6px;
}

.input-group.small .input {
  padding: 8px 0;
  font-size: 13px;
}

.input-group .prefix {
  color: #6b7280;
  font-size: 12px;
  margin-right: 8px;
}

/* 百分比栏 */
.percent-bar {
  display: flex;
  gap: 4px;
  margin-bottom: 12px;
}

.pct-btn {
  flex: 1;
  padding: 6px;
  background: transparent;
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 3px;
  color: #6b7280;
  cursor: pointer;
  font-size: 11px;
}

.pct-btn.active, .pct-btn:hover {
  background: rgba(138, 43, 226, 0.15);
  border-color: rgba(138, 43, 226, 0.3);
  color: #a855f7;
}

/* 🔥 新增: BTC 数量显示 */
.btc-display {
  font-size: 12px;
  color: #6b7280;
  margin: -4px 0 12px 0;
  padding-left: 2px;
}

/* 🔥 新增: 滑块容器 */
.slider-wrapper {
  margin-bottom: 16px;
  padding: 0 4px;
}

/* 🔥 新增: 信息行 */
.info-rows {
  margin-bottom: 16px;
  padding: 12px;
  background: rgba(255, 255, 255, 0.02);
  border-radius: 6px;
  border: 1px solid rgba(255, 255, 255, 0.06);
}

.info-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 4px 0;
}

.info-row:not(:last-child) {
  border-bottom: 1px solid rgba(255, 255, 255, 0.04);
  padding-bottom: 8px;
  margin-bottom: 8px;
}

.info-label {
  color: #6b7280;
  font-size: 12px;
}

.info-value {
  color: #d1d5db;
  font-size: 12px;
  font-family: 'Inter', monospace;
}

.info-value.highlight {
  color: #f59e0b;
  font-weight: 500;
}

/* 止盈止损 */
.tp-sl-section {
  margin-bottom: 12px;
}

.tp-sl-label {
  color: #30b5ff;
  font-size: 12px;
}

.tp-sl-inputs {
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

/* 止盈止损预览 */
.tp-sl-preview {
  margin-top: 10px;
  padding: 10px;
  background: rgba(255, 255, 255, 0.03);
  border-radius: 6px;
  border: 1px solid rgba(255, 255, 255, 0.06);
}

.preview-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}

.preview-row:last-child {
  margin-bottom: 0;
}

.preview-label {
  color: #6b7280;
  font-size: 11px;
}

.preview-value {
  font-size: 12px;
  font-weight: 500;
}

.preview-value.profit {
  color: #22c55e;
}

.preview-value.loss {
  color: #ef4444;
}

.preview-value.ratio {
  color: #eab308;
}

.preview-value .pct {
  margin-left: 4px;
  opacity: 0.8;
  font-size: 11px;
}

/* 选项 */
.options {
  margin-bottom: 12px;
}

.option-label {
  color: #6b7280;
  font-size: 12px;
}

/* 下单按钮 */
.order-buttons {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}

.order-btn {
  flex: 1;
  padding: 12px;
  border-radius: 8px;
  border: none;
  color: #fff;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  font-size: 14px;
  letter-spacing: 0.5px;
  position: relative;
  overflow: hidden;
  box-shadow: 0 2px 6px rgba(0,0,0,0.2);
}

.order-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  background: #333 !important;
  box-shadow: none;
}

.order-btn.long {
  background: linear-gradient(135deg, #16a34a 0%, #22c55e 100%);
  box-shadow: 0 4px 12px rgba(34, 197, 94, 0.2);
}

.order-btn.long:hover:not(:disabled) {
  filter: brightness(1.1);
  transform: translateY(-1px);
  box-shadow: 0 6px 16px rgba(34, 197, 94, 0.3);
}

.order-btn.short {
  background: linear-gradient(135deg, #dc2626 0%, #ef4444 100%);
  box-shadow: 0 4px 12px rgba(239, 68, 68, 0.2);
}

.order-btn.short:hover:not(:disabled) {
  filter: brightness(1.1);
  transform: translateY(-1px);
  box-shadow: 0 6px 16px rgba(239, 68, 68, 0.3);
}

.order-btn:active:not(:disabled) {
  transform: translateY(1px);
}

/* 预估信息 */
.estimates {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px;
  background: #18181b;
  border-radius: 4px;
}

.est-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.est-label {
  color: #6b7280;
  font-size: 11px;
}

.est-value {
  color: #9ca3af;
  font-size: 12px;
}

.est-values {
  display: flex;
  gap: 12px;
}

.est-value.green { color: #22c55e; }
.est-value.red { color: #ef4444; }

/* 杠杆弹窗 */
.leverage-modal {
  padding: 12px 0;
}

.leverage-input-row {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  margin-bottom: 16px;
}

.lev-btn {
  width: 36px;
  height: 36px;
  background: #2a2a30;
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 4px;
  color: white;
  font-size: 18px;
  cursor: pointer;
}

.lev-input {
  width: 80px;
  text-align: center;
  background: transparent;
  border: none;
  color: white;
  font-size: 24px;
  font-weight: 600;
  outline: none;
}

.leverage-presets {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.preset {
  flex: 1;
  min-width: 45px;
  padding: 6px;
  background: #18181b;
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 4px;
  color: #9ca3af;
  cursor: pointer;
  font-size: 11px;
}

.preset.active {
  background: rgba(138, 43, 226, 0.2);
  border-color: rgba(138, 43, 226, 0.4);
  color: #a855f7;
}

.confirm-btn {
  width: 100%;
  padding: 12px;
  background: linear-gradient(135deg, #f59e0b, #ea580c);
  border: none;
  border-radius: 4px;
  color: white;
  font-weight: 600;
  cursor: pointer;
}

.confirm-btn:hover {
  opacity: 0.9;
}

input[type="number"]::-webkit-inner-spin-button,
input[type="number"]::-webkit-outer-spin-button {
  -webkit-appearance: none;
  margin: 0;
}
input[type="number"] {
  -moz-appearance: textfield;
}
</style>
