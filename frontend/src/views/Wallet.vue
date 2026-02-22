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

// Transfer modal
const showTransferModal = ref(false)
const transferAmount = ref<number>(100)
const transferDirection = ref<'to_funding' | 'to_contract'>('to_funding')
const transferLoading = ref(false)

const transferMaxAmount = computed(() => {
  return transferDirection.value === 'to_funding'
    ? walletStore.available
    : walletStore.fundingBalance
})

// ============ Computed ============
const pnl7dColor = computed(() => (stats.value?.pnl_7d ?? 0) >= 0 ? '#00e676' : '#ff1744')

const calendarWeeks = computed(() => {
  if (!stats.value) return []
  const items = stats.value.daily_pnl
  if (items.length === 0) return []

  // Get first day of month (0=Sun)
  const first = items[0]
  if (!first) return []
  const firstDate = new Date(first.date + 'T00:00:00')
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
  const first = stats.value.daily_pnl[0]
  if (!first) return ''
  const d = new Date(first.date + 'T00:00:00')
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

async function handleTransfer() {
  if (!transferAmount.value || transferAmount.value <= 0) return
  transferLoading.value = true
  try {
    const result = await walletStore.transferFunds(transferAmount.value, transferDirection.value)
    if (result.success) {
      showMessage(result.message)
      showTransferModal.value = false
      await fetchStats()
      await fetchTransactions()
    } else {
      showMessage(result.message, 'error')
    }
  } catch (e: any) {
    showMessage('划转失败', 'error')
  } finally {
    transferLoading.value = false
  }
}

function toggleTransferDirection() {
  transferDirection.value = transferDirection.value === 'to_funding' ? 'to_contract' : 'to_funding'
}

// ============ Table Columns ============
function getTypeTag(type: string) {
  const map: Record<string, { label: string; type: any }> = {
    deposit:      { label: '充值', type: 'success' },
    withdraw:     { label: '提现', type: 'warning' },
    freeze:       { label: '冻结', type: 'info' },
    unfreeze:     { label: '解冻', type: 'info' },
    pnl:          { label: '盈亏', type: 'primary' },
    fee:          { label: '手续费', type: 'error' },
    reset:        { label: '重置', type: 'warning' },
    transfer_in:  { label: '转入合约', type: 'success' },
    transfer_out: { label: '转出资金', type: 'warning' },
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

      <!-- ==================== Dual Account Panel ==================== -->
      <div class="dual-account-panel">
        <!-- Contract Account -->
        <div class="account-card contract">
          <div class="account-card-header">
            <!-- Icon removed -->
            <span class="account-title">合约账户</span>
          </div>
          <div class="account-balance">
            <span class="currency-symbol">$</span>{{ walletStore.formattedEquity }}
          </div>
          <div class="account-details">
            <div class="account-detail-item">
              <span class="detail-label">可用</span>
              <span class="detail-value">{{ walletStore.formattedBalance }}</span>
            </div>
            <div class="account-detail-item">
              <span class="detail-label">冻结</span>
              <span class="detail-value">{{ formatNum(walletStore.frozen) }}</span>
            </div>
            <div class="account-detail-item">
              <span class="detail-label">未实现盈亏</span>
              <span class="detail-value" :class="pnlClass(walletStore.unrealizedPnl)">{{ walletStore.formattedUnrealizedPnl }}</span>
            </div>
          </div>
        </div>

        <!-- Transfer Button -->
        <button class="transfer-btn-center" @click="showTransferModal = true" title="划转">
          <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M7 16l-4-4 4-4"/>
            <path d="M17 8l4 4-4 4"/>
            <line x1="3" y1="12" x2="21" y2="12"/>
          </svg>
        </button>

        <!-- Funding Account -->
        <div class="account-card funding">
          <div class="account-card-header">
            <span class="account-icon">🏦</span>
            <span class="account-title">资金账户</span>
          </div>
          <div class="account-balance">
            <span class="currency-symbol">$</span>{{ walletStore.formattedFundingBalance }}
          </div>
          <div class="account-details">
            <div class="account-detail-item">
              <span class="detail-label">可用余额</span>
              <span class="detail-value">{{ walletStore.formattedFundingBalance }}</span>
            </div>
          </div>
        </div>
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

              <div class="mobile-scroll-x">
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
                          <span class="cal-day">{{ parseInt(day.date.split('-')[2] || '0') }}</span>
                          <span class="cal-pnl">{{ day.pnl === 0 ? '-' : (day.pnl > 0 ? '+' : '') + formatNum(day.pnl) }}</span>
                        </template>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
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

      <!-- Transfer Modal -->
      <NModal v-model:show="showTransferModal" preset="card" title="账户划转" style="max-width: 420px;">
        <div class="transfer-form">
          <!-- Direction Display -->
          <div class="transfer-direction">
            <div class="transfer-account-box">
              <span class="transfer-account-label">从</span>
              <span class="transfer-account-name">{{ transferDirection === 'to_funding' ? '合约账户' : '资金账户' }}</span>
              <span class="transfer-account-balance">可用: {{ formatNum(transferMaxAmount) }} USDT</span>
            </div>
            <button class="transfer-swap-btn" @click="toggleTransferDirection" title="切换方向">
              <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M7 3v18"/><path d="m3 7 4-4 4 4"/>
                <path d="M17 21V3"/><path d="m13 17 4 4 4-4"/>
              </svg>
            </button>
            <div class="transfer-account-box">
              <span class="transfer-account-label">到</span>
              <span class="transfer-account-name">{{ transferDirection === 'to_funding' ? '资金账户' : '合约账户' }}</span>
            </div>
          </div>

          <!-- Amount Input -->
          <div class="transfer-amount-section">
            <label class="transfer-input-label">划转金额</label>
            <NInputNumber
              v-model:value="transferAmount"
              :min="0.01"
              :max="transferMaxAmount"
              :show-button="false"
              placeholder="输入金额"
              style="width: 100%;"
            >
              <template #suffix>USDT</template>
            </NInputNumber>
            <div class="transfer-quick-btns">
              <NButton size="tiny" secondary @click="transferAmount = Math.floor(transferMaxAmount * 0.25 * 100) / 100">25%</NButton>
              <NButton size="tiny" secondary @click="transferAmount = Math.floor(transferMaxAmount * 0.5 * 100) / 100">50%</NButton>
              <NButton size="tiny" secondary @click="transferAmount = Math.floor(transferMaxAmount * 0.75 * 100) / 100">75%</NButton>
              <NButton size="tiny" secondary @click="transferAmount = Math.floor(transferMaxAmount * 100) / 100">全部</NButton>
            </div>
          </div>

          <NButton
            type="primary"
            block
            @click="handleTransfer"
            :loading="transferLoading"
            :disabled="!transferAmount || transferAmount <= 0 || transferAmount > transferMaxAmount"
            style="margin-top: 20px;"
          >确认划转</NButton>
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
  overflow-x: hidden;
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

/* ========== Dual Account Panel ========== */
.dual-account-panel {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 24px;
}

.account-card {
  flex: 1;
  background: #111113;
  border-radius: 16px;
  border: 1px solid rgba(255,255,255,0.06);
  padding: 20px;
  transition: border-color 0.2s;
}
.account-card.contract {
  border-left: 3px solid rgba(139, 92, 246, 0.6);
}
.account-card.funding {
  border-left: 3px solid rgba(59, 130, 246, 0.6);
}
.account-card:hover {
  border-color: rgba(255,255,255,0.12);
}
.account-card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}
.account-icon {
  font-size: 18px;
}
.account-title {
  font-size: 14px;
  font-weight: 600;
  color: #9ca3af;
  letter-spacing: 0.5px;
}
.account-balance {
  font-size: 26px;
  font-weight: 700;
  color: #fff;
  font-family: 'Inter', 'SF Mono', monospace;
  margin-bottom: 12px;
}
.account-balance .currency-symbol {
  font-size: 16px;
  color: #6b7280;
  margin-right: 2px;
}
.account-details {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.account-detail-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.account-detail-item .detail-label {
  font-size: 12px;
  color: #6b7280;
}
.account-detail-item .detail-value {
  font-size: 13px;
  color: #d1d5db;
  font-family: 'SF Mono', 'Fira Code', monospace;
}

.transfer-btn-center {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  min-width: 44px;
  border-radius: 50%;
  background: linear-gradient(135deg, rgba(139, 92, 246, 0.2), rgba(59, 130, 246, 0.2));
  border: 1px solid rgba(139, 92, 246, 0.4);
  color: #a78bfa;
  cursor: pointer;
  transition: all 0.2s;
}
.transfer-btn-center:hover {
  background: linear-gradient(135deg, rgba(139, 92, 246, 0.35), rgba(59, 130, 246, 0.35));
  transform: scale(1.1);
  box-shadow: 0 0 20px rgba(139, 92, 246, 0.3);
}

/* ========== Transfer Modal ========== */
.transfer-form {
  padding: 4px 0;
}
.transfer-direction {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  margin-bottom: 20px;
}
.transfer-account-box {
  width: 100%;
  background: rgba(255,255,255,0.03);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 12px;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.transfer-account-label {
  font-size: 11px;
  color: #6b7280;
  text-transform: uppercase;
  letter-spacing: 1px;
}
.transfer-account-name {
  font-size: 15px;
  font-weight: 600;
  color: #e5e7eb;
}
.transfer-account-balance {
  font-size: 12px;
  color: #9ca3af;
  font-family: monospace;
}
.transfer-swap-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: rgba(139, 92, 246, 0.15);
  border: 1px solid rgba(139, 92, 246, 0.3);
  color: #a78bfa;
  cursor: pointer;
  transition: all 0.2s;
  z-index: 1;
}
.transfer-swap-btn:hover {
  background: rgba(139, 92, 246, 0.3);
  transform: rotate(180deg);
}
.transfer-amount-section {
  margin-top: 4px;
}
.transfer-input-label {
  display: block;
  font-size: 13px;
  color: #9ca3af;
  margin-bottom: 8px;
  font-weight: 500;
}
.transfer-quick-btns {
  display: flex;
  gap: 8px;
  margin-top: 10px;
}
.transfer-quick-btns .n-button {
  flex: 1;
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
  border-collapse: separate;
  border-spacing: 6px;       /* Increased spacing */
  table-layout: fixed;
}
.pnl-calendar th {
  color: #a1a1aa; /* Lighter gray for headers */
  font-size: 12px;
  font-weight: 600;
  padding: 8px 4px;
  text-align: center;
  text-transform: uppercase;
  letter-spacing: 1px;
  opacity: 0.8;
}
.pnl-calendar td {
  padding: 8px;
  text-align: center;
  vertical-align: top;
  border: 1px solid rgba(255,255,255,0.05);
  background: rgba(255,255,255,0.03);
  border-radius: 8px;
  height: 64px;
  transition: all 0.2s ease;
  position: relative;
}
.pnl-calendar td:hover:not(.empty) {
  background: rgba(255,255,255,0.08); /* Brighter hover */
  border-color: rgba(255,255,255,0.1);
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0,0,0,0.3);
  z-index: 10;
}
.pnl-calendar td.empty {
  background: transparent;
  border-color: transparent;
  pointer-events: none;
}
/* Positive Day */
.pnl-calendar td.pnl-positive {
  background: rgba(0, 230, 118, 0.08); /* More visible background */
  border: 1px solid rgba(0, 230, 118, 0.2);
}
/* Negative Day */
.pnl-calendar td.pnl-negative {
  background: rgba(255, 23, 68, 0.08);
  border: 1px solid rgba(255, 23, 68, 0.2);
}

.cal-day {
  display: block;
  font-size: 12px;
  font-weight: 600;
  color: #71717a;
  text-align: left;
  line-height: 1;
  margin-bottom: 4px; /* Add spacing */
}
/* Highlight date on active days */
.pnl-positive .cal-day, .pnl-negative .cal-day {
  color: #a1a1aa;
}

.cal-pnl {
  display: block; /* Back to block */
  text-align: right; /* Align right */
  font-size: 13px;
  font-family: 'Inter', monospace;
  font-weight: 700;
  letter-spacing: -0.5px;
  margin-top: auto; /* Push to bottom if height allows, or just margin */
  padding-top: 12px; /* Ensure separation */
}
.pnl-positive .cal-pnl { text-shadow: 0 0 10px rgba(0, 230, 118, 0.3); } /* Glow effect */
.pnl-negative .cal-pnl { text-shadow: 0 0 10px rgba(255, 23, 68, 0.3); }

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
    padding: 8px;
    padding-bottom: calc(5rem + env(safe-area-inset-bottom));
  }
  .overview-row {
    grid-template-columns: 1fr;
    padding: 12px;
    gap: 12px;
  }
  .overview-left {
    border-right: none;
    border-bottom: 1px solid rgba(255,255,255,0.06);
    padding-right: 0;
    padding-bottom: 12px;
  }
  .overview-value {
    font-size: 26px;
  }
  .mini-stats {
    gap: 12px;
  }
  .mini-stat {
    flex-direction: row;
    gap: 6px;
  }
  
  /* Calendar Mobile - Force fit in screen */
  .calendar-section {
    margin-top: 4px;
  }
  .calendar-header {
    margin-bottom: 4px;
  }
  .mobile-scroll-x {
    overflow-x: visible; /* Don't scroll, force fit */
  }
  .pnl-calendar {
    border-spacing: 1px;
    width: 100%;
    table-layout: fixed; /* Force equal column widths */
  }
  .pnl-calendar th {
    font-size: 10px;
    padding: 2px 0;
    letter-spacing: 0;
  }
  .pnl-calendar td {
    height: 44px;
    padding: 2px;
    border-radius: 4px;
    border-width: 0; /* Remove borders to save space */
  }
  .pnl-calendar td:hover:not(.empty) {
    transform: none; /* No hover effect on mobile */
    box-shadow: none;
  }
  .cal-day {
    font-size: 9px;
    margin-bottom: 1px;
  }
  .cal-pnl {
    font-size: 8px;
    letter-spacing: -0.5px;
    padding-top: 4px;
  }
  
  .summary-grid {
    grid-template-columns: 1fr;
  }
  .summary-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 8px;
  }
  .page-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 8px;
    margin-bottom: 12px;
  }
  .fee-item {
    flex-wrap: wrap;
  }
  .dual-account-panel {
    flex-direction: column;
    gap: 10px;
    align-items: stretch;
  }
  .transfer-btn-center {
    transform: rotate(90deg);
    width: 36px;
    height: 36px;
    min-width: 36px;
    align-self: center;
  }
  .account-card {
    flex: none !important;
    width: 100% !important;
    min-width: 0 !important;
    max-width: 100% !important;
    padding: 14px;
    box-sizing: border-box;
    overflow: hidden;
  }
  .account-balance {
    font-size: 22px;
  }
  .account-details {
    width: 100%;
    overflow: hidden;
  }
  .account-detail-item {
    display: flex !important;
    justify-content: space-between !important;
    align-items: center !important;
    width: 100%;
  }
  .account-detail-item .detail-label {
    font-size: 11px;
    flex-shrink: 0;
  }
  .account-detail-item .detail-value {
    font-size: 12px;
    text-align: right;
    flex-shrink: 0;
  }
  .portfolio-page {
    padding: 12px;
  }
  .overview-value {
    font-size: 28px;
  }
  .page-header {
    flex-wrap: wrap;
    gap: 8px;
  }
  .content-grid {
    gap: 16px;
  }
}
</style>
