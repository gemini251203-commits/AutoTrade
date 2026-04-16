<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { createChart, ColorType, CandlestickSeries, HistogramSeries, LineSeries, type IChartApi, type ISeriesApi, type CandlestickData, type Time } from 'lightweight-charts'
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
let volumeSeries: ISeriesApi<'Histogram'> | null = null

// Volume data cache (for updates)
let lastVolumeData: { time: Time; value: number; color: string }[] = []

// Current price for display
const currentPrice = ref(0)
const priceChange = ref(0)
const isPositive = ref(true)
const isLoading = ref(true)

// 支撑阻力线
const showSR = ref(false)
const srLines: any[] = []
const srData = ref<any>(null)

// Vegas Tunnel (EMA 144 / 169)
const showVegas = ref(false)
const vegasInterval = ref('1h')  // 可切换级别
const vegasIntervals = ['15m', '1h', '4h', '1d']
let vegasEma144Series: ISeriesApi<'Line'> | null = null
let vegasEma169Series: ISeriesApi<'Line'> | null = null
let lastKlineRaw: any[] = []  // 缓存原始 kline 数据用于 EMA 计算

// 当前选中的时间周期
const selectedTimeframe = ref('1h')
const timeframes = ['1m', '5m', '15m', '1h', '4h', '1d']

// 使用全局 Symbol Store
const symbolStore = useSymbolStore()
const symbols = SYMBOLS
const symbolMenuOpen = ref(false)

// 从 store 获取当前交易对信息
const currentSymbol = computed(() => symbolStore.currentSymbol)
const currentSymbolInfo = computed((): SymbolInfo => symbolStore.currentSymbolInfo!)


// Handle symbol change
async function handleSymbolChange(symbolCode: string) {
  symbolStore.setSymbol(symbolCode)  // 更新 store
  symbolMenuOpen.value = false
  emit('symbolChange', symbolCode)
  
  // Reload chart data
  if (candlestickSeries) {
    const klines = await fetchKlines(selectedTimeframe.value)
    if (klines && klines.length > 0) {
      candlestickSeries.setData(klines)
      if (volumeSeries) volumeSeries.setData(lastVolumeData)
    } else {
      console.warn('[TradingChart] No data to display')
    }
  }
  // 刷新支撑阻力线 & Vegas
  if (showSR.value) await refreshSR()
  if (showVegas.value) await drawVegas()
}

// 使用封装的 request (自动携带 Token 和处理认证)

// 根据时间周期智能选择 K 线数量
const KLINE_LIMITS: Record<string, number> = {
  '1m': 1440,   // 1天
  '5m': 2016,   // 7天
  '15m': 2016,  // 3周
  '30m': 1440,  // 1月
  '1h': 2016,   // 3月
  '4h': 1095,   // 6月
  '1d': 365,    // 1年
}

// 从后端获取 K 线数据
async function fetchKlines(interval: string = '1h', limit?: number): Promise<CandlestickData<Time>[]> {
  const fetchLimit = limit ?? KLINE_LIMITS[interval] ?? 500
  try {
    isLoading.value = true
    const symbol = symbolStore.currentSymbol  // 使用 store
    
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
    
    // 缓存原始数据用于 EMA 计算
    lastKlineRaw = data
    
    // Volume data for histogram (higher opacity for visibility)
    lastVolumeData = data.map((k: any) => ({
      time: Math.floor(k.open_time / 1000) as Time,
      value: k.volume || 0,
      color: k.close >= k.open
        ? 'rgba(34, 197, 94, 0.6)'    // green (up) — more visible
        : 'rgba(239, 68, 68, 0.6)',    // red (down) — more visible
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
    console.error('[TradingChart] 获取 K 线数据失败:', error)
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
          bottom: 0.35,  // leave room for volume
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
    
    // lightweight-charts v5 新 API
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
    
    // 防止组件销毁后继续操作
    if (isDestroyed || !candlestickSeries || !chart) return
    
    if (klines.length > 0) {
      candlestickSeries.setData(klines)
      
      // Add volume histogram series
      volumeSeries = chart.addSeries(HistogramSeries, {
        priceFormat: { type: 'volume' },
        priceScaleId: 'volume',
      })
      chart.priceScale('volume').applyOptions({
        scaleMargins: { top: 0.7, bottom: 0 },
      })
      volumeSeries.setData(lastVolumeData)
      
      chart.timeScale().fitContent()
    } else {
      console.warn('[TradingChart] 没有获取到数据，请运行 binance_spider.py')
    }
    
  } catch (error) {
    console.error('[TradingChart] K 线图初始化失败:', error)
  }
}

// 切换时间周期
async function changeTimeframe(tf: string) {
  selectedTimeframe.value = tf
  if (candlestickSeries && !isDestroyed) {
    const klines = await fetchKlines(tf)
    if (klines.length > 0 && candlestickSeries && !isDestroyed) {
      candlestickSeries.setData(klines)
      if (volumeSeries) volumeSeries.setData(lastVolumeData)
      chart?.timeScale().fitContent()
    }
  }
  // 刷新支撑阻力线 & Vegas
  if (showSR.value) await refreshSR()
  if (showVegas.value) drawVegas()
}

// ==================== 支撑阻力线 ====================

async function fetchSR() {
  try {
    const res = await request.get('/market/support-resistance', {
      params: {
        symbol: symbolStore.currentSymbol,
        interval: selectedTimeframe.value,
      }
    })
    srData.value = res.data
    return res.data
  } catch (e) {
    console.warn('[TradingChart] 获取支撑阻力失败:', e)
    return null
  }
}

function drawSR(data: any) {
  if (!candlestickSeries || isDestroyed || !data) return
  clearSR()
  
  // 画支撑线 (绿色)
  for (const s of (data.support || []).slice(0, 3)) {
    const line = candlestickSeries.createPriceLine({
      price: s.level,
      color: 'rgba(34, 197, 94, 0.6)',
      lineWidth: 1,
      lineStyle: 2,  // dashed
      axisLabelVisible: true,
      title: `S ${s.strength}x`,
    })
    srLines.push(line)
  }
  
  // 画阻力线 (红色)
  for (const r of (data.resistance || []).slice(0, 3)) {
    const line = candlestickSeries.createPriceLine({
      price: r.level,
      color: 'rgba(239, 68, 68, 0.6)',
      lineWidth: 1,
      lineStyle: 2,  // dashed
      axisLabelVisible: true,
      title: `R ${r.strength}x`,
    })
    srLines.push(line)
  }
}

function clearSR() {
  if (!candlestickSeries) return
  for (const line of srLines) {
    try {
      candlestickSeries.removePriceLine(line)
    } catch { /* already removed */ }
  }
  srLines.length = 0
}

async function toggleSR() {
  showSR.value = !showSR.value
  if (showSR.value) {
    const data = await fetchSR()
    drawSR(data)
  } else {
    clearSR()
    srData.value = null
  }
}

async function refreshSR() {
  if (!showSR.value) return
  const data = await fetchSR()
  drawSR(data)
}

// ==================== Vegas Tunnel ====================

function calcEMA(closes: number[], period: number): (number | null)[] {
  const k = 2 / (period + 1)
  const result: (number | null)[] = []
  let ema: number | null = null
  for (const c of closes) {
    if (ema === null) {
      ema = c
    } else {
      ema = c * k + ema * (1 - k)
    }
    // 需要足够数据才有意义
    result.push(result.length >= period ? ema : null)
  }
  return result
}

async function drawVegas() {
  if (!chart || isDestroyed) return
  clearVegas()

  // 如果 Vegas 级别和当前图表级别不同，需要单独请求数据
  let rawData = lastKlineRaw
  if (vegasInterval.value !== selectedTimeframe.value) {
    try {
      const limit = KLINE_LIMITS[vegasInterval.value] ?? 2016
      const res = await request.get('/market/klines', {
        params: { symbol: symbolStore.currentSymbol, interval: vegasInterval.value, limit }
      })
      rawData = res.data.data || []
    } catch (e) {
      console.warn('[Vegas] fetch failed:', e)
      return
    }
  }

  if (rawData.length < 169) return

  const closes = rawData.map((k: any) => k.close as number)
  const ema144 = calcEMA(closes, 144)
  const ema169 = calcEMA(closes, 169)

  const lineData144: { time: Time; value: number }[] = []
  const lineData169: { time: Time; value: number }[] = []
  for (let i = 0; i < rawData.length; i++) {
    const t = Math.floor(rawData[i].open_time / 1000) as Time
    if (ema144[i] !== null) lineData144.push({ time: t, value: ema144[i]! })
    if (ema169[i] !== null) lineData169.push({ time: t, value: ema169[i]! })
  }

  vegasEma144Series = chart!.addSeries(LineSeries, {
    color: 'rgba(255, 165, 0, 0.8)',  // orange
    lineWidth: 2,
    priceLineVisible: false,
    lastValueVisible: false,
    title: `EMA144 (${vegasInterval.value})`,
  })
  vegasEma169Series = chart!.addSeries(LineSeries, {
    color: 'rgba(0, 191, 255, 0.8)',  // deepskyblue
    lineWidth: 2,
    priceLineVisible: false,
    lastValueVisible: false,
    title: `EMA169 (${vegasInterval.value})`,
  })

  vegasEma144Series.setData(lineData144)
  vegasEma169Series.setData(lineData169)
}

function clearVegas() {
  if (chart && vegasEma144Series) {
    try { chart.removeSeries(vegasEma144Series) } catch {}
  }
  if (chart && vegasEma169Series) {
    try { chart.removeSeries(vegasEma169Series) } catch {}
  }
  vegasEma144Series = null
  vegasEma169Series = null
}

async function toggleVegas() {
  showVegas.value = !showVegas.value
  if (showVegas.value) {
    await drawVegas()
  } else {
    clearVegas()
  }
}

async function changeVegasInterval(interval: string) {
  vegasInterval.value = interval
  if (showVegas.value) {
    await drawVegas()
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
    // 标签页不可见时跳过，节省连接池
    if (document.visibilityState !== 'visible') return
    // 检查组件是否已销毁或图表不存在
    if (isDestroyed || !candlestickSeries || !chart) return
    
    const symbol = symbolStore.currentSymbol  // 使用 store
    
    try {
      // 1. 获取实时行情 (直接从币安获取，最准确)
      const tickerRes = await request.get(`/market/ticker/${symbol}`)
      if (isDestroyed) return  // 请求完成后再次检查
      if (tickerRes.data?.price) {
        currentPrice.value = tickerRes.data.price
        priceChange.value = tickerRes.data.change_percent || 0
        isPositive.value = priceChange.value >= 0
        // 同步更新 store 的价格
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
        // Update volume bar
        if (volumeSeries) {
          volumeSeries.update({
            time: Math.floor(k.open_time / 1000) as Time,
            value: k.volume || 0,
            color: k.close >= k.open
              ? 'rgba(34, 197, 94, 0.6)'
              : 'rgba(239, 68, 68, 0.6)',
          })
        }
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

  // Use ResizeObserver for robust resizing
  const resizeObserver = new ResizeObserver(() => {
    handleResize()
  })
  if (chartContainer.value) {
    resizeObserver.observe(chartContainer.value)
  }
  
  // Store observer for cleanup
  (window as any)._chartResizeObserver = resizeObserver
})

onUnmounted(() => {
  // Cleanup observer
  if ((window as any)._chartResizeObserver) {
    (window as any)._chartResizeObserver.disconnect()
  }

  isDestroyed = true
  if (updateInterval) {
    clearInterval(updateInterval)
    updateInterval = null
  }
  if (chart) {
    chart.remove()
    chart = null
  }
  clearVegas()
  candlestickSeries = null
  volumeSeries = null
})

</script>

<template>
  <div class="relative w-full h-full">
    <!-- Chart Header -->
    <div class="absolute top-0 left-0 right-0 z-10 flex items-center gap-2 p-2 md:gap-4 md:p-4">
      <div class="flex items-center gap-2 md:gap-3 relative">
        <!-- Symbol Selector (Clickable) -->
        <button 
          @click="symbolMenuOpen = !symbolMenuOpen"
          class="flex items-center gap-2 md:gap-3 px-2 py-1.5 rounded-lg hover:bg-white/5 transition-colors"
        >
          <!-- Symbol Icon -->
          <div 
            class="w-6 h-6 md:w-8 md:h-8 rounded-full flex items-center justify-center text-[10px] md:text-xs font-bold text-white"
            :style="{ background: `linear-gradient(135deg, ${currentSymbolInfo.color}, ${currentSymbolInfo.color}dd)` }"
          >
            {{ currentSymbolInfo.letter }}
          </div>
          <div>
            <div class="flex items-center gap-1 md:gap-2">
              <span class="text-white font-medium text-sm md:text-base">{{ currentSymbolInfo.name }}</span>
              <span class="hidden md:inline text-xs text-gray-600">Perpetual</span>
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
      
      <!-- SR Toggle -->
      <button
        @click="toggleSR"
        class="sr-toggle-btn"
        :class="{ active: showSR }"
        title="支撑/阻力线"
      >
        S/R
      </button>

      <!-- Vegas Tunnel Toggle + Level -->
      <div class="flex items-center gap-1">
        <button
          @click="toggleVegas"
          class="sr-toggle-btn"
          :class="{ active: showVegas }"
          title="Vegas Tunnel (EMA 144/169)"
        >
          VGS
        </button>
        <div v-if="showVegas" class="flex gap-0.5">
          <button
            v-for="vi in vegasIntervals"
            :key="vi"
            @click="changeVegasInterval(vi)"
            class="px-1.5 py-0.5 text-[10px] rounded transition-colors cursor-pointer"
            :style="{
              background: vi === vegasInterval ? 'rgba(255, 165, 0, 0.2)' : 'transparent',
              color: vi === vegasInterval ? '#ffa500' : '#6b7280',
            }"
          >
            {{ vi }}
          </button>
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

.sr-toggle-btn {
  padding: 4px 10px;
  font-size: 11px;
  font-weight: 600;
  border-radius: 6px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  background: rgba(255, 255, 255, 0.04);
  color: #6b7280;
  cursor: pointer;
  transition: all 0.2s;
  letter-spacing: 0.5px;
}

.sr-toggle-btn:hover {
  background: rgba(255, 255, 255, 0.08);
  color: #a855f7;
}

.sr-toggle-btn.active {
  background: rgba(138, 43, 226, 0.15);
  border-color: rgba(138, 43, 226, 0.4);
  color: #a855f7;
  box-shadow: 0 0 8px rgba(138, 43, 226, 0.15);
}
</style>
