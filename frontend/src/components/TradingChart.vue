<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { createChart, ColorType, CandlestickSeries, type IChartApi, type ISeriesApi, type CandlestickData, type Time } from 'lightweight-charts'
import request from '@/utils/request'
import { NIcon } from 'naive-ui'
import { ChevronDownOutline } from '@vicons/ionicons5'
import { useSymbolStore, SYMBOLS, type SymbolInfo } from '@/stores/symbol'

const props = defineProps<{
  symbol?: string
}>()

const emit = defineEmits<{
  (e: 'symbolChange', symbol: string): void
}>()

const chartContainer = ref<HTMLDivElement | null>(null)
let chart: IChartApi | null = null
let candlestickSeries: ISeriesApi<'Candlestick'> | null = null

// Current price for display
const currentPrice = ref(0)
const priceChange = ref(0)
const isPositive = ref(true)
const isLoading = ref(true)

// 当前选中的时间周期
const selectedTimeframe = ref('1h')
const timeframes = ['1m', '5m', '15m', '1h', '4h', '1d']

// 🔥 使用全局 Symbol Store
const symbolStore = useSymbolStore()
const symbols = SYMBOLS
const symbolMenuOpen = ref(false)

// 🔥 从 store 获取当前交易对信息
const currentSymbol = computed(() => symbolStore.currentSymbol)
const currentSymbolInfo = computed((): SymbolInfo => symbolStore.currentSymbolInfo!)


// Handle symbol change
async function handleSymbolChange(symbolCode: string) {
  symbolStore.setSymbol(symbolCode)  // 🔥 更新 store
  symbolMenuOpen.value = false
  emit('symbolChange', symbolCode)
  
  // Reload chart data
  if (candlestickSeries) {
    const klines = await fetchKlines(selectedTimeframe.value)
    if (klines && klines.length > 0) {
      candlestickSeries.setData(klines)
    } else {
      console.warn('[TradingChart] ⚠️ No data to display')
    }
  }
}

// 使用封装的 request (自动携带 Token 和处理认证)

// 根据时间周期智能选择 K 线数量
const KLINE_LIMITS: Record<string, number> = {
  '1m': 300,    // 300分钟 ≈ 5小时
  '5m': 500,    // 2500分钟 ≈ 1.7天
  '15m': 500,   // 7500分钟 ≈ 5天
  '1h': 720,    // 720小时 ≈ 30天
  '4h': 720,    // 2880小时 ≈ 120天
  '1d': 1095,   // 1095天 ≈ 3年
}

// 从后端获取 K 线数据
async function fetchKlines(interval: string = '1h', limit?: number): Promise<CandlestickData<Time>[]> {
  const fetchLimit = limit ?? KLINE_LIMITS[interval] ?? 500
  try {
    isLoading.value = true
    const symbol = symbolStore.currentSymbol  // 🔥 使用 store
    
    const response = await request.get('/market/klines', {
      params: {
        symbol: symbol,
        interval: interval,
        limit: fetchLimit,
      }
    })
    
    const data = response.data.data || []
    
    // 转换为 lightweight-charts 格式
    const klines: CandlestickData<Time>[] = data.map((k: any) => ({
      time: Math.floor(k.open_time / 1000) as Time,  // 毫秒转秒
      open: k.open,
      high: k.high,
      low: k.low,
      close: k.close,
    }))
    
    // 更新当前价格
    if (klines.length > 0) {
      const lastKline = klines[klines.length - 1]
      if (lastKline?.close) {
        currentPrice.value = lastKline.close as number
      }
      
      // 计算涨跌幅 (与第一根K线比较)
      const firstClose = klines[0]?.close as number ?? currentPrice.value
      const change = firstClose > 0 ? ((currentPrice.value - firstClose) / firstClose) * 100 : 0
      priceChange.value = Math.round(change * 100) / 100
      isPositive.value = priceChange.value >= 0
    }
    

    return klines
    
  } catch (error) {
    console.error('[TradingChart] ❌ 获取 K 线数据失败:', error)
    return []
  } finally {
    isLoading.value = false
  }
}

// Initialize chart
async function initChart() {
  if (!chartContainer.value) return
  

  
  try {
    chart = createChart(chartContainer.value, {
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: '#6b7280',
        fontFamily: 'Inter, system-ui, sans-serif',
        fontSize: 11,
      },
      grid: {
        vertLines: { color: 'rgba(255, 255, 255, 0.02)' },
        horzLines: { color: 'rgba(255, 255, 255, 0.02)' },
      },
      crosshair: {
        mode: 1,
        vertLine: {
          color: 'rgba(138, 43, 226, 0.5)',
          width: 1,
          style: 2,
          labelBackgroundColor: '#8a2be2',
        },
        horzLine: {
          color: 'rgba(138, 43, 226, 0.5)',
          width: 1,
          style: 2,
          labelBackgroundColor: '#8a2be2',
        },
      },
      rightPriceScale: {
        borderColor: 'rgba(255, 255, 255, 0.05)',
        scaleMargins: {
          top: 0.1,
          bottom: 0.1,
        },
      },
      timeScale: {
        borderColor: 'rgba(255, 255, 255, 0.05)',
        timeVisible: true,
        secondsVisible: false,
      },
      handleScroll: {
        vertTouchDrag: false,
      },
    })
    
    // ✅ lightweight-charts v5 新 API
    candlestickSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#22c55e',
      downColor: '#ef4444',
      borderUpColor: '#22c55e',
      borderDownColor: '#ef4444',
      wickUpColor: '#22c55e',
      wickDownColor: '#ef4444',
    })
    
    // 从后端获取真实数据
    const klines = await fetchKlines(selectedTimeframe.value)
    
    if (klines.length > 0) {
      candlestickSeries.setData(klines)
      chart?.timeScale().fitContent()

    } else {
      console.warn('[TradingChart] ⚠️ 没有获取到数据，请运行 binance_spider.py')
    }
    
  } catch (error) {
    console.error('[TradingChart] ❌ K 线图初始化失败:', error)
  }
}

// 切换时间周期
async function changeTimeframe(tf: string) {
  selectedTimeframe.value = tf
  if (candlestickSeries) {
    const klines = await fetchKlines(tf)
    if (klines.length > 0) {
      candlestickSeries.setData(klines)
      chart?.timeScale().fitContent()
    }
  }
}

// Handle resize
function handleResize() {
  if (chart && chartContainer.value) {
    chart.applyOptions({
      width: chartContainer.value.clientWidth,
      height: chartContainer.value.clientHeight,
    })
  }
}

// 实时更新 (每 5 秒拉取最新行情 + K 线)
let updateInterval: ReturnType<typeof setInterval> | null = null
let isDestroyed = false  // 防止组件销毁后继续更新

function startLiveUpdates() {
  updateInterval = setInterval(async () => {
    // 检查组件是否已销毁或图表不存在
    if (isDestroyed || !candlestickSeries || !chart) return
    
    const symbol = symbolStore.currentSymbol  // 🔥 使用 store
    
    try {
      // 1. 获取实时行情 (直接从币安获取，最准确)
      const tickerRes = await request.get(`/market/ticker/${symbol}`)
      if (isDestroyed) return  // 请求完成后再次检查
      if (tickerRes.data?.price) {
        currentPrice.value = tickerRes.data.price
        priceChange.value = tickerRes.data.change_percent || 0
        isPositive.value = priceChange.value >= 0
        // 🔥 同步更新 store 的价格
        symbolStore.updatePrice(tickerRes.data.price, tickerRes.data.change_percent)
      }
    } catch {
      // 实时行情失败时静默
    }
    
    try {
      // 2. 更新 K 线图
      if (isDestroyed || !candlestickSeries) return  // 再次检查
      const klineRes = await request.get('/market/klines/latest', {
        params: {
          symbol: symbol,
          interval: selectedTimeframe.value,
        }
      })
      
      if (isDestroyed || !candlestickSeries) return  // 请求完成后再次检查
      const k = klineRes.data
      if (k) {
        candlestickSeries.update({
          time: Math.floor(k.open_time / 1000) as Time,
          open: k.open,
          high: k.high,
          low: k.low,
          close: k.close,
        })
      }
    } catch {
      // K 线更新失败时静默
    }
  }, 5000)
}

onMounted(() => {

  isDestroyed = false
  initChart()
  startLiveUpdates()
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {

  isDestroyed = true  // 设置销毁标志
  if (updateInterval) {
    clearInterval(updateInterval)
    updateInterval = null
  }
  if (chart) {
    chart.remove()
    chart = null
  }
  candlestickSeries = null
  window.removeEventListener('resize', handleResize)
})
</script>

<template>
  <div class="relative w-full h-full min-h-[400px]">
    <!-- Chart Header -->
    <div class="absolute top-0 left-0 right-0 z-10 flex items-center gap-4 p-4">
      <div class="flex items-center gap-3 relative">
        <!-- Symbol Selector (Clickable) -->
        <button 
          @click="symbolMenuOpen = !symbolMenuOpen"
          class="flex items-center gap-3 px-2 py-1.5 rounded-lg hover:bg-white/5 transition-colors"
        >
          <!-- Symbol Icon -->
          <div 
            class="w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold text-white"
            :style="{ background: `linear-gradient(135deg, ${currentSymbolInfo.color}, ${currentSymbolInfo.color}dd)` }"
          >
            {{ currentSymbolInfo.letter }}
          </div>
          <div>
            <div class="flex items-center gap-2">
              <span class="text-white font-medium">{{ currentSymbolInfo.name }}</span>
              <span class="text-xs text-gray-600">Perpetual</span>
              <NIcon size="12" class="text-gray-500 transition-transform" :class="symbolMenuOpen ? 'rotate-180' : ''">
                <ChevronDownOutline />
              </NIcon>
            </div>
          </div>
        </button>

        <!-- Symbol Dropdown Menu -->
        <Transition name="dropdown">
          <div 
            v-if="symbolMenuOpen"
            class="absolute top-full left-0 mt-2 w-48 rounded-lg overflow-hidden z-50"
            style="background: #1a1a1f; border: 1px solid rgba(255,255,255,0.1); box-shadow: 0 10px 40px rgba(0,0,0,0.5);"
          >
            <button
              v-for="sym in symbols"
              :key="sym.code"
              @click="handleSymbolChange(sym.code)"
              class="w-full flex items-center gap-3 px-3 py-2.5 hover:bg-white/5 transition-colors"
              :class="currentSymbol === sym.code ? 'bg-purple-500/10' : ''"
            >
              <div 
                class="w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold text-white"
                :style="{ background: sym.color }"
              >
                {{ sym.letter }}
              </div>
              <span class="text-sm text-white">{{ sym.name }}</span>
            </button>
          </div>
        </Transition>
      </div>
      
      <!-- Price Display -->
      <div class="ml-auto flex items-center gap-4">
        <div class="text-right">
          <div v-if="isLoading" class="text-gray-500 text-xl">加载中...</div>
          <template v-else>
            <div class="text-xl font-mono font-semibold" :style="{ color: isPositive ? '#22c55e' : '#ef4444' }">
              ${{ currentPrice.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) }}
            </div>
            <div class="text-xs font-mono" :style="{ color: isPositive ? '#22c55e' : '#ef4444' }">
              {{ isPositive ? '+' : '' }}{{ priceChange }}%
            </div>
          </template>
        </div>
      </div>
      
      <!-- Timeframe Selector -->
      <div class="flex gap-1">
        <button
          v-for="tf in timeframes"
          :key="tf"
          @click="changeTimeframe(tf)"
          class="px-2 py-1 text-xs rounded transition-colors cursor-pointer"
          :style="{
            background: tf === selectedTimeframe ? 'rgba(138, 43, 226, 0.15)' : 'transparent',
            color: tf === selectedTimeframe ? '#a855f7' : '#6b7280',
          }"
        >
          {{ tf }}
        </button>
      </div>
    </div>
    
    <!-- Chart Container -->
    <div 
      ref="chartContainer" 
      class="w-full h-full pt-14"
      style="background: transparent;"
    ></div>
  </div>
</template>

<style scoped>
:deep(.tv-lightweight-charts) {
  width: 100% !important;
  height: 100% !important;
}
</style>
