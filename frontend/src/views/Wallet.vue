<script setup lang="ts">
/**
 * Wallet.vue (Portfolio View)
 * ============================
 * 投资组合页面 — Binance 风格
 *
 * 模块:
 * 1. 投资组合概览 (总价值 / 7日PnL / 7日交易量 / 持仓数)
 * 2. 日历 PnL (当月)
 * 3. 摘要统计 (按时间范围)
 * 4. 存款/重置 + 资金流水
 */
import { ref, onMounted, computed, h } from 'vue'
import {
  NCard, NStatistic, NGrid, NGi, NDataTable, NButton,
  NTag, NSpace, NModal, NInputNumber, NEmpty, NSpin,
  NButtonGroup
} from 'naive-ui'
import MainLayout from '@/layouts/MainLayout.vue'
import { useWalletStore } from '@/stores/wallet'
import request from '@/utils/request'

const walletStore = useWalletStore()

// ============ Types ============
interface DailyPnl {
  date: string
  pnl: number
}

interface TradeSummary {
  total_trades: number
  long_trades: number
  short_trades: number
  total_volume: number
  long_volume: number
  short_volume: number
  total_commission: number
  latest_commission: number
}

interface PortfolioStats {
  total_value: number
  pnl_7d: number
  volume_7d: number
  perpetual_count: number
  daily_pnl: DailyPnl[]
  summary: TradeSummary
  taker_fee_rate: string
  maker_fee_rate: string
}

// ============ State ============
const stats = ref<PortfolioStats | null>(null)
const statsLoading = ref(false)
const selectedPeriod = ref('7d')
const calendarTab = ref<'pnl' | 'value'>('pnl')

const transactions = ref<any[]>([])
const txLoading = ref(false)
const showDepositModal = ref(false)
const depositAmount = ref<number>(1000)
const depositLoading = ref(false)
const resetLoading = ref(false)
const statusMessage = ref('')
const statusType = ref<'success' | 'error' | 'warning'>('success')
const showStatus = ref(false)

// ============ Computed ============
const pnl7dColor = computed(() => (stats.value?.pnl_7d ?? 0) >= 0 ? '#00e676' : '#ff1744')

const calendarWeeks = computed(() => {
  if (!stats.value) return []
  const items = stats.value.daily_pnl
  if (items.length === 0) return []

  // Get first day of month (0=Sun)
  const firstDate = new Date(items[0].date + 'T00:00:00')
  const startDow = firstDate.getDay()

  // Build weeks
  const weeks: (DailyPnl | null)[][] = []
  let week: (DailyPnl | null)[] = Array(startDow).fill(null)

  for (const item of items) {
    week.push(item)
    if (week.length === 7) {
      weeks.push(week)
      week = []
    }
  }
  if (week.length > 0) {
    while (week.length < 7) week.push(null)
    weeks.push(week)
  }
  return weeks
})

const monthLabel = computed(() => {
  if (!stats.value || stats.value.daily_pnl.length === 0) return ''
  const d = new Date(stats.value.daily_pnl[0].date + 'T00:00:00')
  return d.toLocaleDateString('en-US', { month: 'long', year: 'numeric' })
})

// ============ Helpers ============
function showMessage(msg: string, type: 'success' | 'error' | 'warning' = 'success') {
  statusMessage.value = msg
  statusType.value = type
  showStatus.value = true
  setTimeout(() => { showStatus.value = false }, 3000)
}

function formatNum(n: number, decimals = 2): string {
  return new Intl.NumberFormat('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(n)
}

function pnlClass(val: number): string {
  if (val > 0) return 'pnl-positive'
  if (val < 0) return 'pnl-negative'
  return 'pnl-zero'
}

// ============ API ============
async function fetchStats() {
  statsLoading.value = true
  try {
    const resp = await request.get('/wallet/portfolio-stats', {
      params: { period: selectedPeriod.value }
    })
    stats.value = resp.data
  } catch (e) {
    console.error('Failed to fetch portfolio stats:', e)
  } finally {
    statsLoading.value = false
  }
}

async function fetchTransactions() {
  txLoading.value = true
  try {
    const resp = await request.get('/wallet/transactions', { params: { limit: 50 } })
    transactions.value = resp.data
  } catch (e) {
    console.error('Failed to fetch transactions:', e)
  } finally {
    txLoading.value = false
  }
}

async function handleDeposit() {
  if (!depositAmount.value || depositAmount.value <= 0) return
  depositLoading.value = true
  try {
    await request.post('/wallet/deposit', { amount: depositAmount.value })
    showMessage(`充值 ${depositAmount.value} USDT 成功`)
    showDepositModal.value = false
    await walletStore.fetchBalance()
    await fetchStats()
    await fetchTransactions()
  } catch (e: any) {
    showMessage(e.response?.data?.detail || '充值失败', 'error')
  } finally {
    depositLoading.value = false
  }
}

async function handleReset() {
  resetLoading.value = true
  try {
    await request.post('/wallet/reset')
    showMessage('账户已重置', 'warning')
    await walletStore.fetchBalance()
    await fetchStats()
    await fetchTransactions()
  } catch (e: any) {
    showMessage(e.response?.data?.detail || '重置失败', 'error')
  } finally {
    resetLoading.value = false
  }
}

function selectPeriod(p: string) {
  selectedPeriod.value = p
  fetchStats()
}

// ============ Table Columns ============
function getTypeTag(type: string) {
  const map: Record<string, { label: string; type: any }> = {
    deposit:  { label: '充值', type: 'success' },
    withdraw: { label: '提现', type: 'warning' },
    freeze:   { label: '冻结', type: 'info' },
    unfreeze: { label: '解冻', type: 'info' },
    pnl:      { label: '盈亏', type: 'primary' },
    fee:      { label: '手续费', type: 'error' },
    reset:    { label: '重置', type: 'warning' },
  }
  return map[type] || { label: type, type: 'default' }
}

const columns = [
  {
    title: '时间',
    key: 'created_at',
    width: 180,
    render(row: any) {
      return new Date(row.created_at).toLocaleString()
    },
  },
  {
    title: '类型',
    key: 'type',
    width: 100,
    render(row: any) {
      const tag = getTypeTag(row.type)
      return h(NTag, { size: 'small', type: tag.type, bordered: false }, () => tag.label)
    },
  },
  {
    title: '金额',
    key: 'amount',
    width: 150,
    render(row: any) {
      const val = parseFloat(row.amount) || 0
      const color = val >= 0 ? '#22c55e' : '#ef4444'
      const sign = val >= 0 ? '+' : ''
      return h('span', { style: { color, fontFamily: 'monospace', fontWeight: 500 } }, sign + formatNum(val, 4))
    },
  },
  {
    title: '余额',
    key: 'balance_after',
    width: 150,
    render(row: any) {
      const val = parseFloat(row.balance_after) || 0
      return h('span', { style: { fontFamily: 'monospace' } }, formatNum(val, 2))
    },
  },
  {
    title: '备注',
    key: 'note',
    ellipsis: { tooltip: true },
  },
]

// ============ Lifecycle ============
onMounted(async () => {
  await walletStore.fetchBalance()
  await fetchStats()
  await fetchTransactions()
})
</script>

<template>
  <MainLayout>
    <div class="portfolio-page">
      <!-- Toast -->
      <Transition name="toast">
        <div v-if="showStatus" class="toast-message" :class="statusType">
          {{ statusMessage }}
        </div>
      </Transition>

      <!-- Page Header -->
      <div class="page-header">
        <h1 class="page-title">投资组合</h1>
        <NSpace>
          <NButton type="primary" secondary @click="showDepositModal = true">存款</NButton>
          <NButton type="warning" secondary @click="handleReset" :loading="resetLoading">重置账户</NButton>
        </NSpace>
      </div>

      <NSpin :show="statsLoading && !stats">
        <div v-if="stats" class="content-grid">

          <!-- ==================== TOP: Overview ==================== -->
          <div class="overview-row">
            <!-- Left: Total Value -->
            <div class="overview-left">
              <div class="overview-label">总价值</div>
              <div class="overview-value">
                <span class="currency-symbol">$</span>{{ formatNum(stats.total_value) }}
                <button class="refresh-btn" @click="fetchStats" title="刷新">
                  <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.5 2v6h-6M2.5 22v-6h6M2 11.5a10 10 0 0 1 18.8-4.3M22 12.5a10 10 0 0 1-18.8 4.2"/></svg>
                </button>
              </div>

              <div class="mini-stats">
                <div class="mini-stat">
                  <span class="mini-label">盈亏 (7天)</span>
                  <span class="mini-value" :class="pnlClass(stats.pnl_7d)">
                    {{ stats.pnl_7d >= 0 ? '+' : '' }}{{ formatNum(stats.pnl_7d) }}
                  </span>
                </div>
                <div class="mini-stat">
                  <span class="mini-label">交易量 (7天)</span>
                  <span class="mini-value">{{ formatNum(stats.volume_7d) }}</span>
                </div>
                <div class="mini-stat">
                  <span class="mini-label">永续</span>
                  <span class="mini-value">{{ stats.perpetual_count }}</span>
                </div>
              </div>
            </div>

            <!-- Right: Calendar PnL -->
            <div class="calendar-section">
              <div class="calendar-header">
                <div class="calendar-tabs">
                  <button :class="{ active: calendarTab === 'pnl' }" @click="calendarTab = 'pnl'">盈亏</button>
                </div>
                <div class="calendar-month">{{ monthLabel }}</div>
              </div>

              <table class="pnl-calendar">
                <thead>
                  <tr>
                    <th v-for="d in ['日', '一', '二', '三', '四', '五', '六']" :key="d">{{ d }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(week, wi) in calendarWeeks" :key="wi">
                    <td v-for="(day, di) in week" :key="di" :class="day ? pnlClass(day.pnl) : 'empty'">
                      <template v-if="day">
                        <span class="cal-day">{{ parseInt(day.date.split('-')[2]) }}</span>
                        <span class="cal-pnl">{{ day.pnl === 0 ? '0.00' : (day.pnl > 0 ? '+' : '') + formatNum(day.pnl) }}</span>
                      </template>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <!-- ==================== MIDDLE: Summary ==================== -->
          <div class="summary-section">
            <div class="summary-header">
              <h2 class="section-title">摘要</h2>
              <div class="period-buttons">
                <button v-for="p in [
                  { key: '24h', label: '24小时' },
                  { key: '7d', label: '7天' },
                  { key: '14d', label: '14天' },
                  { key: '30d', label: '30天' },
                  { key: 'all', label: '所有时间' },
                ]" :key="p.key"
                  :class="{ active: selectedPeriod === p.key }"
                  @click="selectPeriod(p.key)"
                >{{ p.label }}</button>
              </div>
            </div>

            <div class="summary-grid">
              <div class="summary-card">
                <div class="summary-card-title">交易总数</div>
                <div class="summary-card-value">{{ stats.summary.total_trades || '--' }}</div>
                <div class="summary-card-detail">
                  <span class="detail-long">做多 <b>{{ stats.summary.long_trades || '--' }}</b></span>
                  <span class="detail-short">做空 <b>{{ stats.summary.short_trades || '--' }}</b></span>
                </div>
              </div>

              <div class="summary-card">
                <div class="summary-card-title">交易总量</div>
                <div class="summary-card-value">{{ stats.summary.total_volume ? formatNum(stats.summary.total_volume) : '--' }}</div>
                <div class="summary-card-detail">
                  <span class="detail-long">做多 <b>{{ stats.summary.long_volume ? formatNum(stats.summary.long_volume) : '--' }}</b></span>
                  <span class="detail-short">做空 <b>{{ stats.summary.short_volume ? formatNum(stats.summary.short_volume) : '--' }}</b></span>
                </div>
              </div>

              <div class="summary-card highlight">
                <div class="summary-card-title" style="color: #f59e0b;">总手续费</div>
                <div class="summary-card-value" style="color: #f59e0b;">{{ stats.summary.total_commission ? formatNum(stats.summary.total_commission) : '--' }}</div>
                <div class="summary-card-detail">
                  <span>最新手续费 <b>{{ stats.summary.latest_commission ? formatNum(stats.summary.latest_commission, 4) : '--' }}</b></span>
                </div>
              </div>
            </div>

            <!-- Fee Rates -->
            <div class="fee-rates">
              <div class="fee-item">
                <span class="fee-label">永续</span>
                <span class="fee-detail">吃单手续费 / 挂单手续费</span>
                <span class="fee-value">{{ stats.taker_fee_rate }} / {{ stats.maker_fee_rate }}</span>
              </div>
            </div>
          </div>

          <!-- ==================== BOTTOM: Transactions ==================== -->
          <div class="transactions-section">
            <div class="section-header">
              <h2 class="section-title">资金流水</h2>
              <NButton size="small" quaternary @click="fetchTransactions" :loading="txLoading">刷新</NButton>
            </div>

            <NDataTable
              v-if="transactions.length"
              :columns="columns"
              :data="transactions"
              :bordered="false"
              :single-line="false"
              size="small"
              :pagination="{ pageSize: 10 }"
              :theme-overrides="{
                thColor: 'transparent',
                tdColor: 'transparent',
                thTextColor: '#9ca3af',
                tdTextColor: '#e5e7eb',
                borderColor: 'rgba(255,255,255,0.05)',
              }"
            />
            <NEmpty v-else description="暂无流水记录" />
          </div>
        </div>
      </NSpin>

      <!-- Deposit Modal -->
      <NModal v-model:show="showDepositModal" preset="card" title="充值" style="max-width: 400px;">
        <div class="deposit-form">
          <p style="color: #9ca3af; margin-bottom: 16px;">输入充值金额 (模拟资金)</p>
          <NInputNumber
            v-model:value="depositAmount"
            :min="1"
            :max="1000000"
            :show-button="false"
            placeholder="金额 USDT"
            style="width: 100%;"
          >
            <template #suffix>USDT</template>
          </NInputNumber>
          <div class="quick-amounts">
            <NButton v-for="amt in [1000, 5000, 10000, 50000]" :key="amt"
              size="small" secondary @click="depositAmount = amt"
            >{{ amt.toLocaleString() }}</NButton>
          </div>
          <NButton
            type="primary"
            block
            @click="handleDeposit"
            :loading="depositLoading"
            style="margin-top: 24px;"
          >确认充值</NButton>
        </div>
      </NModal>
    </div>
  </MainLayout>
</template>

<style scoped>
.portfolio-page {
  padding: 24px;
  max-width: 1400px;
  margin: 0 auto;
  position: relative;
}

/* Toast */
.toast-message {
  position: fixed;
  top: 24px;
  left: 50%;
  transform: translateX(-50%);
  padding: 12px 24px;
  border-radius: 8px;
  font-size: 14px;
  z-index: 1000;
  backdrop-filter: blur(12px);
}
.toast-message.success { background: rgba(34, 197, 94, 0.2); color: #22c55e; border: 1px solid rgba(34, 197, 94, 0.3); }
.toast-message.error   { background: rgba(239, 68, 68, 0.2); color: #ef4444; border: 1px solid rgba(239, 68, 68, 0.3); }
.toast-message.warning { background: rgba(245, 158, 11, 0.2); color: #f59e0b; border: 1px solid rgba(245, 158, 11, 0.3); }
.toast-enter-active, .toast-leave-active { transition: all 0.3s; }
.toast-enter-from, .toast-leave-to { opacity: 0; transform: translateX(-50%) translateY(-20px); }

/* Header */
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
}
.page-title {
  font-size: 28px;
  font-weight: 700;
  color: #fff;
  letter-spacing: -0.5px;
}

/* Content */
.content-grid {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

/* ========== Overview Row ========== */
.overview-row {
  display: grid;
  grid-template-columns: 320px 1fr;
  gap: 24px;
  background: #111113;
  border-radius: 16px;
  border: 1px solid rgba(255,255,255,0.06);
  padding: 24px;
}

.overview-left {
  border-right: 1px solid rgba(255,255,255,0.06);
  padding-right: 24px;
}
.overview-label {
  color: #9ca3af;
  font-size: 14px;
  font-weight: 500;
  margin-bottom: 4px;
}
.overview-value {
  font-size: 32px;
  font-weight: 700;
  color: #fff;
  font-family: 'Inter', monospace;
  display: flex;
  align-items: center;
  gap: 8px;
  letter-spacing: -1px;
}
.currency-symbol {
  color: #6b7280;
  font-weight: 400;
  font-size: 24px;
}
.refresh-btn {
  background: none;
  border: none;
  color: #6b7280;
  cursor: pointer;
  padding: 4px;
  border-radius: 6px;
  transition: all 0.2s;
}
.refresh-btn:hover {
  color: #fff;
  background: rgba(255,255,255,0.1);
}

.mini-stats {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-top: 20px;
}
.mini-stat {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.mini-label {
  color: #6b7280;
  font-size: 13px;
}
.mini-value {
  font-family: 'Inter', monospace;
  font-size: 14px;
  font-weight: 600;
  color: #e5e7eb;
}

/* PnL Colors */
.pnl-positive { color: #00e676 !important; }
.pnl-negative { color: #ff1744 !important; }
.pnl-zero { color: #6b7280 !important; }

/* ========== Calendar ========== */
.calendar-section {
  overflow: hidden;
}
.calendar-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.calendar-tabs {
  display: flex;
  gap: 0;
}
.calendar-tabs button {
  background: rgba(255,255,255,0.05);
  border: 1px solid rgba(255,255,255,0.1);
  color: #9ca3af;
  padding: 6px 16px;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
}
.calendar-tabs button:first-child { border-radius: 8px 0 0 8px; }
.calendar-tabs button:last-child { border-radius: 0 8px 8px 0; }
.calendar-tabs button.active {
  background: rgba(255,255,255,0.1);
  color: #fff;
  border-color: rgba(255,255,255,0.2);
}
.calendar-month {
  color: #9ca3af;
  font-size: 14px;
  font-weight: 500;
}

.pnl-calendar {
  width: 100%;
  border-collapse: collapse;
  table-layout: fixed;
}
.pnl-calendar th {
  color: #6b7280;
  font-size: 12px;
  font-weight: 500;
  padding: 6px 4px;
  text-align: center;
}
.pnl-calendar td {
  padding: 8px 4px;
  text-align: center;
  vertical-align: top;
  border: 1px solid rgba(255,255,255,0.04);
  height: 52px;
  transition: background 0.2s;
}
.pnl-calendar td:hover:not(.empty) {
  background: rgba(255,255,255,0.04);
}
.pnl-calendar td.empty {
  background: transparent;
  border-color: transparent;
}
.pnl-calendar td.pnl-positive {
  background: rgba(0, 230, 118, 0.06);
}
.pnl-calendar td.pnl-negative {
  background: rgba(255, 23, 68, 0.06);
}
.cal-day {
  display: block;
  font-size: 12px;
  color: #9ca3af;
  margin-bottom: 2px;
}
.cal-pnl {
  display: block;
  font-size: 11px;
  font-family: 'Inter', monospace;
  font-weight: 500;
}

/* ========== Summary ========== */
.summary-section {
  background: #111113;
  border-radius: 16px;
  border: 1px solid rgba(255,255,255,0.06);
  padding: 24px;
}
.summary-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}
.section-title {
  font-size: 18px;
  font-weight: 600;
  color: #fff;
}
.period-buttons {
  display: flex;
  gap: 0;
}
.period-buttons button {
  background: rgba(255,255,255,0.05);
  border: 1px solid rgba(255,255,255,0.1);
  color: #9ca3af;
  padding: 6px 14px;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s;
}
.period-buttons button:first-child { border-radius: 8px 0 0 8px; }
.period-buttons button:last-child { border-radius: 0 8px 8px 0; }
.period-buttons button.active {
  background: rgba(255,255,255,0.1);
  color: #fff;
  border-color: rgba(255,255,255,0.2);
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  margin-bottom: 20px;
}
.summary-card {
  background: rgba(255,255,255,0.03);
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 12px;
  padding: 20px;
}
.summary-card-title {
  font-size: 13px;
  color: #9ca3af;
  margin-bottom: 8px;
  font-weight: 500;
}
.summary-card-value {
  font-size: 24px;
  font-weight: 700;
  color: #fff;
  font-family: 'Inter', monospace;
  margin-bottom: 12px;
  letter-spacing: -0.5px;
}
.summary-card-detail {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 13px;
}
.detail-long {
  color: #00e676;
}
.detail-short {
  color: #ff1744;
}
.summary-card-detail b {
  font-weight: 600;
}
.summary-card-detail span {
  color: #9ca3af;
}

/* Fee Rates */
.fee-rates {
  border-top: 1px solid rgba(255,255,255,0.06);
  padding-top: 16px;
}
.fee-item {
  display: flex;
  align-items: center;
  gap: 16px;
  font-size: 13px;
}
.fee-label {
  color: #9ca3af;
  font-weight: 500;
  min-width: 40px;
}
.fee-detail {
  color: #6b7280;
}
.fee-value {
  color: #e5e7eb;
  font-family: 'Inter', monospace;
  font-weight: 500;
  margin-left: auto;
}

/* ========== Transactions ========== */
.transactions-section {
  background: #111113;
  border-radius: 16px;
  border: 1px solid rgba(255,255,255,0.06);
  padding: 24px;
}
.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

/* Deposit */
.quick-amounts {
  display: flex;
  gap: 8px;
  margin-top: 12px;
}
.deposit-form {
  padding: 8px 0;
}

/* ========== Responsive ========== */
@media (max-width: 768px) {
  .portfolio-page {
    padding: 16px;
  }
  .overview-row {
    grid-template-columns: 1fr;
    padding: 16px;
  }
  .overview-left {
    border-right: none;
    border-bottom: 1px solid rgba(255,255,255,0.06);
    padding-right: 0;
    padding-bottom: 16px;
  }
  .summary-grid {
    grid-template-columns: 1fr;
  }
  .summary-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 12px;
  }
  .page-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 12px;
  }
  .fee-item {
    flex-wrap: wrap;
  }
}
</style>
