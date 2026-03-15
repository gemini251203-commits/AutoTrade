<script setup lang="ts">
/**
 * TradeJournal.vue
 * =================
 * 交易日志 - 统一交易记忆系统
 * 
 * 展示所有来源 (手动/AI Agent/信号助手/量化策略) 的交易记录
 * 包含统计卡片 + 记忆列表
 */
import { ref, onMounted, computed, nextTick } from 'vue'
import { NTag, NEmpty, NSpin, NSelect, NTooltip, NIcon, NPopconfirm, NPagination, NButton, NModal, useMessage } from 'naive-ui'
import { BookOutline, TrendingUpOutline, TrendingDownOutline, TimeOutline, ShieldCheckmarkOutline, TrashOutline, DownloadOutline, ChevronBackOutline, ChevronForwardOutline } from '@vicons/ionicons5'
import MainLayout from '@/layouts/MainLayout.vue'
import request from '@/utils/request'
import type { TradeMemoryResponse as TradeMemory } from '@/api/strategy'
import { formatDateTimeBJ } from '@/utils/time'

// ========== Types ==========
// TradeMemory imported from '@/api/strategy' as TradeMemoryResponse

interface JournalStats {
  total_trades: number
  win_count: number
  loss_count: number
  win_rate: number
  total_pnl_usdt: number
  avg_pnl_pct: number
  avg_duration_min: number | null
  by_source: Record<string, { count: number; pnl_usdt: number }>
}

// ========== State ==========
const memories = ref<TradeMemory[]>([])
const stats = ref<JournalStats | null>(null)
const loading = ref(false)
const symbolFilter = ref('')
const sourceFilter = ref<string | null>(null)
const resultFilter = ref<string | null>(null)
const message = useMessage()

// ========== Pagination ==========
const currentPage = ref(1)
const pageSize = ref(20)
const totalItems = ref(0)

// ========== Options ==========
const sourceOptions = [
  { label: '全部来源', value: '' },
  { label: '手动交易', value: 'manual' },
  { label: 'AI Agent', value: 'agent' },
  { label: 'AI Hub', value: 'hub' },
  { label: 'Autopilot', value: 'autopilot' },
  { label: '信号助手', value: 'signal' },
  { label: '量化策略', value: 'quant' },
  { label: '网格交易', value: 'grid' },
  { label: '新闻监控', value: 'news_monitor' },
  { label: '系统操作', value: 'system' },
]

const resultOptions = [
  { label: '全部结果', value: '' },
  { label: '盈利', value: 'win' },
  { label: '亏损', value: 'loss' },
  { label: '持平', value: 'breakeven' },
]

// ========== Labels ==========
const sourceLabels: Record<string, string> = {
  manual: '手动',
  agent: 'AI Agent',
  hub: 'AI Hub',
  autopilot: 'Autopilot',
  signal: '信号助手',
  quant: '量化策略',
  grid: '网格',
  news_monitor: '新闻监控',
  system: '系统',
}

const sourceColors: Record<string, string> = {
  manual: '#6b7280',
  agent: '#8b5cf6',
  hub: '#6366f1',
  autopilot: '#f97316',
  signal: '#3b82f6',
  quant: '#10b981',
  grid: '#ec4899',
  news_monitor: '#14b8a6',
  system: '#f59e0b',
}

const closeReasonLabels: Record<string, string> = {
  manual: '手动平仓',
  agent: 'AI Agent 平仓',
  autopilot: 'Autopilot 平仓',
  tp_hit: '止盈触发',
  sl_hit: '止损触发',
  stop_loss: '止损触发',
  take_profit: '止盈触发',
  liquidated: '强平',
  signal: '信号平仓',
  strategy: '策略平仓',
  account_reset: '账户重置',
}

// ========== Fetch ==========
async function fetchAll() {
  loading.value = true
  try {
    const params: Record<string, string | number> = {
      limit: pageSize.value,
      offset: (currentPage.value - 1) * pageSize.value,
    }
    if (symbolFilter.value) params.symbol = symbolFilter.value.trim().toUpperCase()
    if (sourceFilter.value) params.source = sourceFilter.value
    if (resultFilter.value) params.result = resultFilter.value
    
    const [memRes, statRes] = await Promise.all([
      request.get('/journal/', { params }),
      request.get('/journal/stats', { params: symbolFilter.value ? { symbol: symbolFilter.value.trim().toUpperCase() } : {} }),
    ])
    memories.value = memRes.data.items
    totalItems.value = memRes.data.total
    stats.value = statRes.data
  } catch (e) {
    console.error('Failed to fetch journal:', e)
  } finally {
    loading.value = false
  }
}

function onFilterChange() {
  currentPage.value = 1
  fetchAll()
}

function onPageChange(page: number) {
  currentPage.value = page
  fetchAll()
}

async function deleteMemory(id: number) {
  try {
    await request.delete(`/journal/${id}`)
    message.success('已删除')
    fetchAll()
  } catch (e) {
    message.error('删除失败')
  }
}

// ========== Helpers ==========
function formatDuration(min: number | null): string {
  if (min === null || min === undefined) return '-'
  const m = Math.round(min)
  if (m < 60) return `${m}分钟`
  const hours = Math.floor(m / 60)
  const mins = m % 60
  if (m < 1440) return `${hours}小时${mins > 0 ? mins + '分' : ''}`
  const days = Math.floor(m / 1440)
  const remHours = Math.floor((m % 1440) / 60)
  return `${days}天${remHours}小时`
}

function formatPrice(price: string | number | null | undefined): string {
  if (price === null || price === undefined) return '-'
  const n = typeof price === 'string' ? parseFloat(price) : price
  if (isNaN(n)) return '-'
  if (n >= 1000) return n.toFixed(1)
  if (n >= 1) return n.toFixed(2)
  return n.toFixed(4)
}

const formatTime = formatDateTimeBJ

// ========== Poster Export ==========
const showPosterModal = ref(false)
const posterGenerating = ref(false)
const posterCanvas = ref<HTMLCanvasElement | null>(null)
const posterPreviewUrl = ref('')

// Calendar state
const pCalYear = ref(new Date().getFullYear())
const pCalMonth = ref(new Date().getMonth() + 1)
const pCalMonthLabel = computed(() => `${pCalYear.value} 年 ${pCalMonth.value} 月`)

interface DailyPnlItem { date: string; pnl: number }
const dailyPnlData = ref<DailyPnlItem[]>([])
const dailyPnlMap = computed(() => {
  const map: Record<string, number> = {}
  // 北京时间今天
  const now = new Date()
  const bj = new Date(now.getTime() + 8 * 3600000)
  const todayStr = `${bj.getUTCFullYear()}-${String(bj.getUTCMonth() + 1).padStart(2, '0')}-${String(bj.getUTCDate()).padStart(2, '0')}`
  for (const d of dailyPnlData.value) {
    // 只显示今天及之前的日期
    if (d.date <= todayStr) map[d.date] = d.pnl
  }
  return map
})

const pCalendarWeeks = computed(() => {
  const y = pCalYear.value, m = pCalMonth.value
  const firstDay = new Date(y, m - 1, 1)
  const daysInMonth = new Date(y, m, 0).getDate()
  const startDow = firstDay.getDay()
  const weeks: (number | null)[][] = []
  let week: (number | null)[] = Array(startDow).fill(null)
  for (let d = 1; d <= daysInMonth; d++) {
    week.push(d)
    if (week.length === 7) { weeks.push(week); week = [] }
  }
  if (week.length > 0) {
    while (week.length < 7) week.push(null)
    weeks.push(week)
  }
  return weeks
})

function pDateStr(day: number): string {
  return `${pCalYear.value}-${String(pCalMonth.value).padStart(2, '0')}-${String(day).padStart(2, '0')}`
}

async function openPosterModal() {
  const now = new Date()
  const bj = new Date(now.getTime() + 8 * 3600000)
  pCalYear.value = bj.getUTCFullYear()
  pCalMonth.value = bj.getUTCMonth() + 1
  showPosterModal.value = true
  posterPreviewUrl.value = ''
  await fetchPosterPnl()
}

async function fetchPosterPnl() {
  try {
    const res = await request.get('/wallet/portfolio-stats')
    dailyPnlData.value = res.data.daily_pnl || []
  } catch { dailyPnlData.value = [] }
}

function pCalPrev() {
  if (pCalMonth.value === 1) { pCalYear.value--; pCalMonth.value = 12 }
  else pCalMonth.value--
  fetchPosterPnl()
}
function pCalNext() {
  if (pCalMonth.value === 12) { pCalYear.value++; pCalMonth.value = 1 }
  else pCalMonth.value++
  fetchPosterPnl()
}

interface PosterTrade {
  symbol: string; side: string; leverage: number
  entry_price: number; exit_price: number
  pnl_pct: number; pnl_usdt: number
}

async function selectPosterDay(day: number) {
  const dateStr = pDateStr(day)
  posterGenerating.value = true
  posterPreviewUrl.value = ''
  try {
    // 获取当日盈亏
    const pnlValue = dailyPnlMap.value[dateStr] || 0

    // 获取收益率
    const walletRes = await request.get('/wallet/balance')
    const initialBalance = parseFloat(String(walletRes.data.initial_balance)) || 3000
    const pnlPct = initialBalance > 0 ? (pnlValue / initialBalance) * 100 : 0

    // 获取当日交易列表
    const journalRes = await request.get('/journal/', {
      params: { limit: 50, offset: 0 }
    })
    const allTrades: TradeMemory[] = journalRes.data?.items || []
    
    // 筛选当日交易（按北京时间）
    const dayTrades: PosterTrade[] = allTrades
      .filter(m => {
        if (!m.created_at) return false
        const t = new Date(m.created_at)
        const bj = new Date(t.getTime() + 8 * 3600000)
        const bjDate = `${bj.getUTCFullYear()}-${String(bj.getUTCMonth() + 1).padStart(2, '0')}-${String(bj.getUTCDate()).padStart(2, '0')}`
        return bjDate === dateStr
      })
      .filter(m => m.source !== 'system')
      .map(m => ({
        symbol: m.symbol,
        side: m.side || 'long',
        leverage: m.leverage || 1,
        entry_price: parseFloat(String(m.entry_price || 0)),
        exit_price: parseFloat(String(m.exit_price || 0)),
        pnl_pct: parseFloat(String(m.pnl_pct || 0)),
        pnl_usdt: parseFloat(String(m.pnl_usdt || 0)),
      }))

    await nextTick()
    drawPoster(dateStr, pnlValue, pnlPct, dayTrades)
  } catch (e) {
    console.error('Failed to generate poster:', e)
    message.error('生成海报失败')
  } finally {
    posterGenerating.value = false
  }
}

function fmtPrice(p: number): string {
  if (p >= 1000) return p.toFixed(1)
  if (p >= 1) return p.toFixed(2)
  return p.toFixed(4)
}

function drawPoster(dateStr: string, pnlValue: number, pnlPct: number, trades: PosterTrade[]) {
  const canvas = posterCanvas.value
  if (!canvas) return
  const dpr = 2
  const W = 400
  // 高度自适应：基础 380 + 每笔交易（限8笔）55px + 溢出摘要行 + 底部 90
  const displayCount = Math.min(trades.length, 8)
  const hasExtra = trades.length > 8
  const tradeAreaH = Math.max(displayCount * 55 + (hasExtra ? 30 : 0), 40)
  const H = 380 + tradeAreaH + 90
  canvas.width = W * dpr
  canvas.height = H * dpr
  canvas.style.width = W + 'px'
  canvas.style.height = H + 'px'
  const ctx = canvas.getContext('2d')!
  ctx.scale(dpr, dpr)

  const isPositive = pnlValue >= 0
  const accentColor = isPositive ? '#0ECB81' : '#F6465D'

  // ---- Background ----
  ctx.fillStyle = '#0B0E11'
  ctx.fillRect(0, 0, W, H)

  // 装饰菱形
  ctx.save()
  ctx.translate(W - 80, 90)
  ctx.rotate(Math.PI / 4)
  ctx.strokeStyle = 'rgba(255,255,255,0.04)'
  ctx.lineWidth = 2
  ctx.strokeRect(-55, -55, 110, 110)
  ctx.fillStyle = 'rgba(255,255,255,0.02)'
  ctx.fillRect(-40, -40, 80, 80)
  ctx.restore()

  // ---- Date ----
  ctx.fillStyle = '#848E9C'
  ctx.font = '14px -apple-system, "Helvetica Neue", sans-serif'
  ctx.fillText(dateStr, 32, 42)

  // ---- Title ----
  ctx.fillStyle = '#EAECEF'
  ctx.font = 'bold 22px -apple-system, "Helvetica Neue", sans-serif'
  ctx.fillText('AutoTrade 日收益', 32, 85)

  // ---- Subtitle ----
  ctx.fillStyle = '#848E9C'
  ctx.font = '14px -apple-system, "Helvetica Neue", sans-serif'
  const wins = trades.filter(t => t.pnl_usdt > 0).length
  const losses = trades.filter(t => t.pnl_usdt < 0).length
  if (trades.length > 0) {
    ctx.fillText(`${trades.length} 笔交易 · ${wins}胜 ${losses}负`, 32, 112)
  } else {
    ctx.fillText('当日无交易', 32, 112)
  }

  // ---- Main PnL ----
  const sign = isPositive ? '+' : ''
  const pnlText = `${sign}${pnlValue.toFixed(2)}`
  ctx.fillStyle = accentColor
  ctx.font = 'bold 48px -apple-system, "Helvetica Neue", sans-serif'
  ctx.fillText(pnlText, 32, 195)
  const pnlWidth = ctx.measureText(pnlText).width
  ctx.fillStyle = '#848E9C'
  ctx.font = '18px -apple-system, "Helvetica Neue", sans-serif'
  ctx.fillText('USDT', 32 + pnlWidth + 8, 195)

  // ---- PnL Percentage ----
  ctx.fillStyle = accentColor
  ctx.font = 'bold 24px -apple-system, "Helvetica Neue", sans-serif'
  ctx.fillText(`${sign}${pnlPct.toFixed(2)}%`, 32, 235)

  // ---- Divider ----
  let curY = 265
  ctx.strokeStyle = 'rgba(255,255,255,0.06)'
  ctx.lineWidth = 1
  ctx.beginPath()
  ctx.moveTo(32, curY)
  ctx.lineTo(W - 32, curY)
  ctx.stroke()
  curY += 20

  // ---- Trade list (max 8) ----
  const MAX_POSTER_TRADES = 8
  const showTrades = trades.slice(0, MAX_POSTER_TRADES)
  const extraCount = trades.length - showTrades.length

  if (showTrades.length > 0) {
    // 表头
    ctx.fillStyle = '#5E6673'
    ctx.font = '11px -apple-system, "Helvetica Neue", sans-serif'
    ctx.fillText('交易对', 32, curY)
    ctx.fillText('方向/杠杆', 130, curY)
    ctx.fillText('入场 → 出场', 215, curY)
    ctx.textAlign = 'right'
    ctx.fillText('盈亏', W - 32, curY)
    ctx.textAlign = 'left'
    curY += 16

    for (const t of showTrades) {
      // Symbol
      ctx.fillStyle = '#EAECEF'
      ctx.font = 'bold 13px -apple-system, "Helvetica Neue", sans-serif'
      ctx.fillText(t.symbol.replace('USDT', ''), 32, curY)

      // Side + leverage
      const sideText = t.side === 'long' ? '多' : '空'
      const sideColor = t.side === 'long' ? '#0ECB81' : '#F6465D'
      ctx.fillStyle = sideColor
      ctx.font = 'bold 12px -apple-system, "Helvetica Neue", sans-serif'
      ctx.fillText(`${sideText} ${t.leverage}x`, 130, curY)

      // Entry → Exit
      ctx.fillStyle = '#848E9C'
      ctx.font = '11px -apple-system, "Helvetica Neue", sans-serif'
      ctx.fillText(`${fmtPrice(t.entry_price)} → ${fmtPrice(t.exit_price)}`, 215, curY)

      // PnL
      const tSign = t.pnl_usdt >= 0 ? '+' : ''
      ctx.fillStyle = t.pnl_usdt >= 0 ? '#0ECB81' : '#F6465D'
      ctx.font = 'bold 12px -apple-system, "Helvetica Neue", sans-serif'
      ctx.textAlign = 'right'
      ctx.fillText(`${tSign}${t.pnl_usdt.toFixed(2)}`, W - 32, curY)
      ctx.textAlign = 'left'

      // PnL pct (下方小字)
      ctx.fillStyle = t.pnl_pct >= 0 ? 'rgba(14,203,129,0.6)' : 'rgba(246,70,93,0.6)'
      ctx.font = '10px -apple-system, "Helvetica Neue", sans-serif'
      ctx.textAlign = 'right'
      ctx.fillText(`${t.pnl_pct >= 0 ? '+' : ''}${t.pnl_pct.toFixed(1)}%`, W - 32, curY + 14)
      ctx.textAlign = 'left'

      curY += 38
    }

    // 超出部分摘要
    if (extraCount > 0) {
      ctx.fillStyle = '#5E6673'
      ctx.font = '12px -apple-system, "Helvetica Neue", sans-serif'
      const extraPnl = trades.slice(MAX_POSTER_TRADES).reduce((s, t) => s + t.pnl_usdt, 0)
      const extraSign = extraPnl >= 0 ? '+' : ''
      ctx.fillText(`... 及其他 ${extraCount} 笔交易`, 32, curY)
      ctx.fillStyle = extraPnl >= 0 ? '#0ECB81' : '#F6465D'
      ctx.font = 'bold 12px -apple-system, "Helvetica Neue", sans-serif'
      ctx.textAlign = 'right'
      ctx.fillText(`${extraSign}${extraPnl.toFixed(2)}`, W - 32, curY)
      ctx.textAlign = 'left'
      curY += 24
    }
  } else {
    ctx.fillStyle = '#5E6673'
    ctx.font = '13px -apple-system, "Helvetica Neue", sans-serif'
    ctx.fillText('当日暂无已平仓交易记录', 32, curY + 10)
  }

  // ---- Footer divider ----
  ctx.strokeStyle = 'rgba(255,255,255,0.06)'
  ctx.beginPath()
  ctx.moveTo(32, H - 70)
  ctx.lineTo(W - 32, H - 70)
  ctx.stroke()

  // ---- Footer watermark ----
  ctx.fillStyle = '#848E9C'
  ctx.font = '13px -apple-system, "Helvetica Neue", sans-serif'
  ctx.fillText('AutoTrade · AI 量化交易系统', 32, H - 40)
  ctx.fillStyle = '#5E6673'
  ctx.font = '11px -apple-system, "Helvetica Neue", sans-serif'
  ctx.fillText('Powered by AI Agent', 32, H - 20)

  posterPreviewUrl.value = canvas.toDataURL('image/png')
}

function downloadPoster() {
  if (!posterPreviewUrl.value) return
  const dateStr = `${pCalYear.value}${String(pCalMonth.value).padStart(2, '0')}`
  const a = document.createElement('a')
  a.href = posterPreviewUrl.value
  a.download = `AutoTrade_${dateStr}.png`
  a.click()
}

onMounted(fetchAll)
</script>

<template>
  <MainLayout>
    <div class="journal-page">
      <!-- Header -->
      <div class="journal-header">
        <div class="header-left">
          <NIcon size="24" color="#8b5cf6"><BookOutline /></NIcon>
          <h1>交易日志</h1>
          <span class="subtitle" v-if="stats">共 {{ stats.total_trades }} 笔交易</span>
          <NButton size="small" quaternary @click="openPosterModal" style="margin-left: 8px;">
            <template #icon><NIcon><DownloadOutline /></NIcon></template>
            导出海报
          </NButton>
        </div>
        <div class="header-filters">
          <NInput
            v-model:value="symbolFilter"
            placeholder="搜索交易对"
            size="small"
            clearable
            style="width: 120px"
            @keyup.enter="onFilterChange"
            @clear="onFilterChange"
          >
            <template #prefix>
              <NIcon><SearchOutline /></NIcon>
            </template>
          </NInput>
          <NSelect
            v-model:value="sourceFilter"
            :options="sourceOptions"
            placeholder="来源"
            size="small"
            clearable
            style="width: 130px"
            @update:value="onFilterChange"
          />
          <NSelect
            v-model:value="resultFilter"
            :options="resultOptions"
            placeholder="结果"
            size="small"
            clearable
            style="width: 110px"
            @update:value="onFilterChange"
          />
        </div>
      </div>

      <!-- Stats Cards -->
      <div class="stats-grid" v-if="stats && stats.total_trades > 0">
        <div class="stat-card">
          <div class="stat-icon win">
            <NIcon size="20"><TrendingUpOutline /></NIcon>
          </div>
          <div>
            <div class="stat-value" :style="{ color: stats.total_pnl_usdt >= 0 ? '#22c55e' : '#ef4444' }">
              {{ stats.total_pnl_usdt >= 0 ? '+' : '' }}{{ stats.total_pnl_usdt.toFixed(2) }} USDT
            </div>
            <div class="stat-label">总盈亏</div>
          </div>
        </div>
        
        <div class="stat-card">
          <div class="stat-icon rate">
            <NIcon size="20"><ShieldCheckmarkOutline /></NIcon>
          </div>
          <div>
            <div class="stat-value">{{ stats.win_rate.toFixed(1) }}%</div>
            <div class="stat-label">胜率 ({{ stats.win_count }}W / {{ stats.loss_count }}L)</div>
          </div>
        </div>
        
        <div class="stat-card">
          <div class="stat-icon avg">
            <NIcon size="20"><TrendingDownOutline /></NIcon>
          </div>
          <div>
            <div class="stat-value">{{ stats.avg_pnl_pct >= 0 ? '+' : '' }}{{ stats.avg_pnl_pct.toFixed(2) }}%</div>
            <div class="stat-label">平均收益率</div>
          </div>
        </div>
        
        <div class="stat-card">
          <div class="stat-icon time">
            <NIcon size="20"><TimeOutline /></NIcon>
          </div>
          <div>
            <div class="stat-value">{{ formatDuration(stats.avg_duration_min ?? null) }}</div>
            <div class="stat-label">平均持仓</div>
          </div>
        </div>
      </div>

      <!-- Source Breakdown -->
      <div class="source-breakdown" v-if="stats && Object.keys(stats.by_source).length > 1">
        <div 
          v-for="(data, src) in stats.by_source" 
          :key="src"
          class="source-chip"
          :style="{ borderColor: sourceColors[src] || '#6b7280' }"
        >
          <span class="source-dot" :style="{ background: sourceColors[src] || '#6b7280' }"></span>
          <span>{{ sourceLabels[src] || src }}</span>
          <span class="chip-count">{{ data.count }}笔</span>
          <span class="chip-pnl" :style="{ color: data.pnl_usdt >= 0 ? '#22c55e' : '#ef4444' }">
            {{ data.pnl_usdt >= 0 ? '+' : '' }}{{ data.pnl_usdt.toFixed(2) }}
          </span>
        </div>
      </div>

      <!-- Symbol Analysis Cards (Pure Frontend Computed from memories) -->
      <div class="symbol-analysis-grid" v-if="memories.length > 0 && !symbolFilter">
        <div class="analysis-title">活跃交易对分析</div>
        <div class="analysis-cards">
          <div
            v-for="sym in Object.keys(memories.reduce((acc, m) => {
              if(!acc[m.symbol]) acc[m.symbol] = { w:0, t:0, pnl:0 };
              acc[m.symbol]!.t++;
              if(m.trade_result === 'win') acc[m.symbol]!.w++;
              acc[m.symbol]!.pnl += parseFloat(String(m.pnl_usdt || 0));
              return acc;
            }, {} as Record<string, any>)).sort((a,b) => {
              const d = memories.reduce((acc, m) => { acc[m.symbol] = (acc[m.symbol] || 0) + 1; return acc; }, {} as Record<string, number>);
              return (d[b] || 0) - (d[a] || 0);
            }).slice(0, 4)"
            :key="sym"
            class="symbol-stat-card"
          >
            <div class="sym-name mono">{{ sym }}</div>
            <div class="sym-data">
              <span class="sym-rate">{{ Math.round((memories.filter(m => m.symbol === sym && m.trade_result === 'win').length / memories.filter(m => m.symbol === sym).length) * 100) }}% 胜率</span>
              <span class="sym-pnl mono" :style="{ color: memories.filter(m => m.symbol === sym).reduce((s, m) => s + parseFloat(String(m.pnl_usdt || 0)), 0)! >= 0 ? '#22c55e' : '#ef4444' }">
                {{ memories.filter(m => m.symbol === sym).reduce((s, m) => s + parseFloat(String(m.pnl_usdt || 0)), 0)! >= 0 ? '+' : '' }}{{ memories.filter(m => m.symbol === sym).reduce((s, m) => s + parseFloat(String(m.pnl_usdt || 0)), 0)!.toFixed(2) }}
              </span>
            </div>
          </div>
        </div>
      </div>

      <!-- Source PnL Bar Chart -->
      <div class="source-pnl-chart" v-if="stats && Object.keys(stats.by_source).length > 1">
        <div class="chart-title">来源盈亏对比</div>
        <div class="chart-bars">
          <div
            v-for="(data, src) in stats.by_source"
            :key="src"
            class="bar-row"
          >
            <span class="bar-label">{{ sourceLabels[src] || src }}</span>
            <div class="bar-track">
              <div
                class="bar-fill"
                :style="{
                  width: Math.min(Math.abs(data.pnl_usdt) / Math.max(...Object.values(stats!.by_source).map(d => Math.abs(d.pnl_usdt)), 1) * 100, 100) + '%',
                  background: data.pnl_usdt >= 0
                    ? `linear-gradient(90deg, ${sourceColors[src] || '#6b7280'}88, ${sourceColors[src] || '#6b7280'})`
                    : 'linear-gradient(90deg, #ef444488, #ef4444)',
                }"
              />
            </div>
            <span class="bar-value" :style="{ color: data.pnl_usdt >= 0 ? '#22c55e' : '#ef4444' }">
              {{ data.pnl_usdt >= 0 ? '+' : '' }}{{ data.pnl_usdt.toFixed(2) }}
            </span>
          </div>
        </div>
      </div>

      <!-- Loading -->
      <div class="loading-container" v-if="loading">
        <NSpin size="medium" />
      </div>

      <!-- Empty State -->
      <div v-else-if="memories.length === 0" class="empty-state">
        <NEmpty description="暂无交易记录" />
        <p class="empty-hint">开仓并平仓后，交易记忆将自动生成</p>
      </div>

      <!-- Memory List -->
      <div class="memory-list" v-else>
        <div 
          v-for="mem in memories" 
          :key="mem.id"
          class="memory-card"
          :class="{ 'win': mem.trade_result === 'win', 'loss': mem.trade_result === 'loss' }"
        >
          <!-- Row 1: Symbol, Source, Result -->
          <div class="mem-header">
            <div class="mem-symbol">
              <span class="result-dot" :class="mem.trade_result"></span>
              {{ mem.symbol }}
              <NTag 
                size="tiny" 
                :bordered="false"
                :style="{ background: (sourceColors[mem.source || ''] || '#6b7280') + '20', color: sourceColors[mem.source || ''] || '#6b7280' }"
              >
                {{ sourceLabels[mem.source || ''] || mem.source || '未知' }}
              </NTag>
              <NTag v-if="mem.side" size="tiny" :bordered="false" :type="mem.side === 'long' ? 'success' : 'error'">
                {{ mem.side === 'long' ? '做多' : '做空' }}
              </NTag>
              <NTag v-if="mem.leverage" size="tiny" :bordered="false" style="background: rgba(139,92,246,0.15); color: #a78bfa;">
                {{ mem.leverage }}x
              </NTag>
              <NTag v-if="mem.close_reason === 'account_reset'" size="tiny" :bordered="false" style="background: rgba(245,158,11,0.15); color: #f59e0b;">
                账户重置
              </NTag>
            </div>
            <div style="display: flex; align-items: center; gap: 8px;">
              <div class="mem-pnl" :class="mem.trade_result">
                <span class="pnl-pct">{{ parseFloat(String(mem.pnl_pct)) >= 0 ? '+' : '' }}{{ parseFloat(String(mem.pnl_pct)).toFixed(2) }}%</span>
                <span class="pnl-usdt" v-if="mem.pnl_usdt !== null">
                  {{ parseFloat(String(mem.pnl_usdt)) >= 0 ? '+' : '' }}{{ parseFloat(String(mem.pnl_usdt)).toFixed(2) }} USDT
                </span>
              </div>
              <NPopconfirm @positive-click="deleteMemory(mem.id)">
                <template #trigger>
                  <span class="delete-btn"><NIcon size="14"><TrashOutline /></NIcon></span>
                </template>
                确定删除这条记录？
              </NPopconfirm>
            </div>
          </div>

          <!-- Row 2: Details -->
          <div class="mem-details" v-if="mem.source !== 'system'">
            <div class="detail-item">
              <span class="detail-label">入场</span>
              <span class="detail-value">{{ formatPrice(mem.entry_price) }}</span>
            </div>
            <div class="detail-item">
              <span class="detail-label">出场</span>
              <span class="detail-value">{{ formatPrice(mem.exit_price) }}</span>
            </div>
            <div class="detail-item">
              <span class="detail-label">时长</span>
              <span class="detail-value">{{ formatDuration(mem.duration_minutes) }}</span>
            </div>
            <div class="detail-item" v-if="mem.close_reason">
              <span class="detail-label">平仓</span>
              <span class="detail-value">{{ closeReasonLabels[mem.close_reason] || mem.close_reason }}</span>
            </div>
            <div class="detail-item risk-icons">
              <NTooltip v-if="mem.had_stop_loss">
                <template #trigger>
                  <span class="risk-badge sl">SL</span>
                </template>
                已设置止损
              </NTooltip>
              <NTooltip v-if="mem.had_take_profit">
                <template #trigger>
                  <span class="risk-badge tp">TP</span>
                </template>
                已设置止盈
              </NTooltip>
              <span v-if="!mem.had_stop_loss && !mem.had_take_profit" class="risk-badge none">无风控</span>
            </div>
            <div class="detail-item time-item">
              <span class="detail-value muted">{{ formatTime(mem.created_at) }}</span>
            </div>
          </div>
          <!-- System entry (reset etc) -->
          <div class="mem-details" v-else>
            <div class="detail-item">
              <span class="detail-value">{{ mem.open_reason }}</span>
            </div>
            <div class="detail-item time-item">
              <span class="detail-value muted">{{ formatTime(mem.created_at) }}</span>
            </div>
          </div>

          <!-- Row 3: Reason (collapsible) -->
          <div class="mem-reason" v-if="mem.open_reason && mem.source !== 'system'">
            <span class="reason-label">理由:</span>
            {{ mem.open_reason }}
          </div>
          <div class="mem-lesson" v-if="mem.lesson">
            <span class="reason-label">教训:</span>
            {{ mem.lesson }}
          </div>
        </div>
      </div>

      <!-- Pagination -->
      <div class="pagination-container" v-if="totalItems > pageSize">
        <NPagination
          :page="currentPage"
          :page-size="pageSize"
          :item-count="totalItems"
          :page-slot="7"
          @update:page="onPageChange"
        />
      </div>

      <!-- Poster Export Modal -->
      <NModal v-model:show="showPosterModal" preset="card" title="导出收益海报" style="max-width: 720px; max-height: 90vh;" :bordered="false">
        <div class="poster-modal-body">
          <!-- Calendar Header -->
          <div class="poster-cal-header">
            <button class="cal-nav-btn" @click="pCalPrev">
              <NIcon :component="ChevronBackOutline" :size="18" />
            </button>
            <span class="cal-month-label">{{ pCalMonthLabel }}</span>
            <button class="cal-nav-btn" @click="pCalNext">
              <NIcon :component="ChevronForwardOutline" :size="18" />
            </button>
          </div>
          <!-- Calendar Grid -->
          <NSpin :show="posterGenerating">
            <table class="poster-cal-table">
              <thead>
                <tr>
                  <th v-for="d in ['日','一','二','三','四','五','六']" :key="d">{{ d }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(week, wi) in pCalendarWeeks" :key="wi">
                  <td v-for="(day, di) in week" :key="di">
                    <div
                      v-if="day"
                      @click="selectPosterDay(day as number)"
                      class="cal-day-cell"
                      :style="dailyPnlMap[pDateStr(day as number)] !== undefined ? {
                        background: (dailyPnlMap[pDateStr(day as number)] ?? 0) >= 0 ? 'rgba(34,197,94,0.15)' : 'rgba(239,68,68,0.15)',
                        border: '1px solid ' + ((dailyPnlMap[pDateStr(day as number)] ?? 0) >= 0 ? 'rgba(34,197,94,0.3)' : 'rgba(239,68,68,0.3)'),
                      } : {}"
                    >
                      <span class="cal-day-num">{{ day }}</span>
                      <span
                        v-if="dailyPnlMap[pDateStr(day as number)] !== undefined"
                        class="cal-day-pnl"
                        :style="{ color: (dailyPnlMap[pDateStr(day as number)] ?? 0) >= 0 ? '#22c55e' : '#ef4444' }"
                      >
                        {{ (dailyPnlMap[pDateStr(day as number)] ?? 0) >= 0 ? '+' : '' }}{{ (dailyPnlMap[pDateStr(day as number)] ?? 0).toFixed(1) }}
                      </span>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </NSpin>
          <div class="poster-cal-hint" v-if="!posterPreviewUrl">点击日历上的日期生成海报</div>
          <!-- Preview -->
          <div class="poster-preview" v-if="posterPreviewUrl">
            <img :src="posterPreviewUrl" alt="poster" class="poster-img" />
            <NButton type="primary" block @click="downloadPoster" style="margin-top: 12px;">
              <template #icon><NIcon><DownloadOutline /></NIcon></template>
              保存图片
            </NButton>
          </div>
          <canvas ref="posterCanvas" style="display: none;" />
        </div>
      </NModal>
    </div>
  </MainLayout>
</template>

<style scoped>
.journal-page {
  max-width: 1000px;
  margin: 0 auto;
}

.journal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.header-left h1 {
  font-size: 20px;
  font-weight: 600;
  color: #e5e7eb;
  margin: 0;
}

.subtitle {
  font-size: 13px;
  color: #6b7280;
}

.header-filters {
  display: flex;
  gap: 8px;
}

/* Stats Grid */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 16px;
}

.stat-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.06);
}

.stat-icon {
  width: 36px;
  height: 36px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.stat-icon.win { background: rgba(34, 197, 94, 0.15); color: #22c55e; }
.stat-icon.rate { background: rgba(139, 92, 246, 0.15); color: #8b5cf6; }
.stat-icon.avg { background: rgba(59, 130, 246, 0.15); color: #3b82f6; }
.stat-icon.time { background: rgba(245, 158, 11, 0.15); color: #f59e0b; }

.stat-value {
  font-size: 16px;
  font-weight: 600;
  color: #e5e7eb;
  font-family: 'SF Mono', monospace;
}

.stat-label {
  font-size: 11px;
  color: #6b7280;
  margin-top: 2px;
}

/* Source Breakdown */
.source-breakdown {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.source-chip {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 10px;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid;
  font-size: 12px;
  color: #9ca3af;
}

.source-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
}

.chip-count { color: #6b7280; }
.chip-pnl { font-family: 'SF Mono', monospace; font-weight: 500; }

/* Source PnL Bar Chart */
.source-pnl-chart {
  padding: 14px 16px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.02);
  border: 1px solid rgba(255, 255, 255, 0.06);
  margin-bottom: 16px;
}

.chart-title {
  font-size: 12px;
  color: #6b7280;
  margin-bottom: 12px;
  font-weight: 500;
}

.chart-bars {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.bar-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.bar-label {
  font-size: 12px;
  color: #9ca3af;
  width: 70px;
  flex-shrink: 0;
  text-align: right;
}

.bar-track {
  flex: 1;
  height: 18px;
  background: rgba(255, 255, 255, 0.03);
  border-radius: 4px;
  overflow: hidden;
}

.bar-fill {
  height: 100%;
  border-radius: 4px;
  transition: width 0.6s cubic-bezier(0.22, 1, 0.36, 1);
  min-width: 2px;
}

.bar-value {
  font-size: 12px;
  font-family: 'SF Mono', monospace;
  font-weight: 600;
  width: 80px;
  flex-shrink: 0;
  text-align: right;
}

/* Symbol Analysis */
.symbol-analysis-grid {
  margin-bottom: 16px;
}
.analysis-title {
  font-size: 12px;
  color: #6b7280;
  margin-bottom: 8px;
  font-weight: 500;
}
.analysis-cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 12px;
}
.symbol-stat-card {
  padding: 12px 14px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.02);
  border: 1px solid rgba(255, 255, 255, 0.05);
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.sym-name {
  font-weight: 600;
  color: #e5e7eb;
}
.sym-data {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 2px;
}
.sym-rate {
  font-size: 11px;
  color: #9ca3af;
}
.sym-pnl {
  font-size: 13px;
  font-weight: 600;
}

/* Loading */
.loading-container {
  display: flex;
  justify-content: center;
  padding: 60px 0;
}

.empty-state {
  text-align: center;
  padding: 60px 0;
}

.empty-hint {
  font-size: 13px;
  color: #4b5563;
  margin-top: 8px;
}

/* Memory Cards */
.memory-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.memory-card {
  padding: 14px 16px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.02);
  border: 1px solid rgba(255, 255, 255, 0.05);
  transition: background 0.2s;
}

.memory-card:hover {
  background: rgba(255, 255, 255, 0.04);
}

.memory-card.win {
  border-left: 3px solid rgba(34, 197, 94, 0.5);
}

.memory-card.loss {
  border-left: 3px solid rgba(239, 68, 68, 0.5);
}

.mem-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.mem-symbol {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  font-weight: 600;
  color: #e5e7eb;
}

.result-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.result-dot.win { background: #22c55e; }
.result-dot.loss { background: #ef4444; }
.result-dot.breakeven { background: #6b7280; }

.mem-pnl {
  text-align: right;
  font-family: 'SF Mono', monospace;
}

.mem-pnl.win { color: #22c55e; }
.mem-pnl.loss { color: #ef4444; }
.mem-pnl.breakeven { color: #6b7280; }

.delete-btn {
  cursor: pointer;
  color: #4b5563;
  opacity: 0;
  transition: all 0.2s;
  padding: 4px;
  border-radius: 4px;
}

.memory-card:hover .delete-btn {
  opacity: 1;
}

.delete-btn:hover {
  color: #ef4444;
  background: rgba(239, 68, 68, 0.1);
}

.pnl-pct {
  font-size: 15px;
  font-weight: 600;
}

.pnl-usdt {
  display: block;
  font-size: 12px;
  opacity: 0.7;
}

.mem-details {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}

.detail-item {
  display: flex;
  align-items: center;
  gap: 4px;
}

.detail-label {
  font-size: 11px;
  color: #6b7280;
}

.detail-value {
  font-size: 12px;
  color: #9ca3af;
  font-family: 'SF Mono', monospace;
}

.detail-value.muted {
  color: #4b5563;
}

.risk-icons {
  display: flex;
  gap: 4px;
}

.risk-badge {
  font-size: 10px;
  font-weight: 600;
  padding: 1px 5px;
  border-radius: 3px;
}

.risk-badge.sl { background: rgba(239, 68, 68, 0.15); color: #f87171; }
.risk-badge.tp { background: rgba(34, 197, 94, 0.15); color: #4ade80; }
.risk-badge.none { background: rgba(107, 114, 128, 0.15); color: #6b7280; font-weight: 400; }

.time-item {
  margin-left: auto;
}

.mem-reason,
.mem-lesson {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid rgba(255, 255, 255, 0.04);
  font-size: 12px;
  color: #6b7280;
  line-height: 1.6;
}

.reason-label {
  color: #4b5563;
  font-weight: 500;
}

/* Pagination */
.pagination-container {
  display: flex;
  justify-content: center;
  margin-top: 20px;
  padding-bottom: 20px;
}

@media (max-width: 768px) {
  .stats-grid {
    grid-template-columns: repeat(2, 1fr);
    gap: 8px;
  }
  .stat-card {
    padding: 10px;
  }
  .journal-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 10px;
  }
  .journal-page {
    padding-bottom: calc(5rem + env(safe-area-inset-bottom));
  }
  .memory-card {
    padding: 12px;
  }
  .mem-header {
    flex-wrap: wrap;
    gap: 6px;
  }
  .mem-stats {
    flex-wrap: wrap;
    gap: 8px;
  }
  .source-breakdown {
    flex-wrap: wrap;
    gap: 6px;
  }
}

/* Poster Modal */
.poster-modal-body {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.poster-cal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.cal-nav-btn {
  padding: 4px;
  border-radius: 6px;
  background: none;
  border: none;
  color: #9ca3af;
  cursor: pointer;
  transition: background 0.2s;
}
.cal-nav-btn:hover {
  background: rgba(255,255,255,0.1);
}

.cal-month-label {
  font-size: 14px;
  font-weight: 700;
  color: #e5e7eb;
}

.poster-cal-table {
  width: 100%;
  border-collapse: collapse;
  text-align: center;
}

.poster-cal-table th {
  font-size: 10px;
  color: #6b7280;
  padding: 4px 0;
  font-weight: 400;
}

.poster-cal-table td {
  padding: 3px;
}

.cal-day-cell {
  margin: 0 auto;
  width: 44px;
  height: 44px;
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.2s;
  border: 1px solid transparent;
}

.cal-day-cell:hover {
  background: rgba(255,255,255,0.08);
}

.cal-day-num {
  font-size: 12px;
  color: #d1d5db;
}

.cal-day-pnl {
  font-size: 8px;
  font-family: 'SF Mono', monospace;
  font-weight: 600;
}

.poster-cal-hint {
  text-align: center;
  font-size: 12px;
  color: #6b7280;
  padding: 8px 0;
}

.poster-preview {
  display: flex;
  flex-direction: column;
  align-items: center;
  max-height: 50vh;
  overflow-y: auto;
}

.poster-img {
  width: 100%;
  max-width: 400px;
  border-radius: 8px;
  box-shadow: 0 4px 24px rgba(0,0,0,0.4);
}
</style>
