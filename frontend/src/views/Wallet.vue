<script setup lang="ts">
/**
 * Wallet.vue
 * ===========
 * 钱包管理页面
 */
import { ref, onMounted, computed, h } from 'vue'
import { 
  NCard, NStatistic, NGrid, NGi, NDataTable, NButton, 
  NTag, NSpace, NModal, NInputNumber, NEmpty
} from 'naive-ui'
import MainLayout from '@/layouts/MainLayout.vue'
import { useWalletStore } from '@/stores/wallet'
import request from '@/utils/request'

const walletStore = useWalletStore()

// ============ State ============
const transactions = ref<any[]>([])
const loading = ref(false)
const showDepositModal = ref(false)
const depositAmount = ref<number>(1000)
const depositLoading = ref(false)
const resetLoading = ref(false)
const statusMessage = ref('')
const statusType = ref<'success' | 'error' | 'warning'>('success')
const showStatus = ref(false)

// ============ Computed ============
const pnlColor = computed(() => walletStore.totalPnl >= 0 ? '#22c55e' : '#ef4444')

// ============ Status Message ============
function showMessage(msg: string, type: 'success' | 'error' | 'warning' = 'success') {
  statusMessage.value = msg
  statusType.value = type
  showStatus.value = true
  setTimeout(() => { showStatus.value = false }, 3000)
}

// ============ API Calls ============
async function fetchTransactions() {
  loading.value = true
  try {
    const resp = await request.get('/wallet/transactions', { params: { limit: 50 } })
    transactions.value = resp.data
  } catch (e) {
    console.error('Failed to fetch transactions:', e)
  } finally {
    loading.value = false
  }
}

async function handleDeposit() {
  if (depositAmount.value <= 0) {
    showMessage('请输入有效金额', 'warning')
    return
  }
  
  depositLoading.value = true
  try {
    await request.post('/wallet/deposit', { amount: depositAmount.value })
    showMessage(`充值 ${depositAmount.value} USDT 成功`, 'success')
    showDepositModal.value = false
    await walletStore.fetchBalance()
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
    showMessage('钱包已重置', 'success')
    await walletStore.fetchBalance()
    await fetchTransactions()
  } catch (e: any) {
    showMessage(e.response?.data?.detail || '重置失败', 'error')
  } finally {
    resetLoading.value = false
  }
}

// ============ Table Columns ============
function getTypeTag(type: string) {
  const map: Record<string, { label: string; color: string }> = {
    deposit: { label: '充值', color: '#22c55e' },
    withdraw: { label: '提现', color: '#ef4444' },
    freeze: { label: '冻结', color: '#f59e0b' },
    unfreeze: { label: '解冻', color: '#3b82f6' },
    pnl: { label: '盈亏', color: '#a855f7' },
    fee: { label: '手续费', color: '#6b7280' },
    reset: { label: '重置', color: '#ec4899' },
  }
  const info = map[type] || { label: type, color: '#6b7280' }
  return h(NTag, { 
    size: 'small', 
    style: { background: info.color + '20', color: info.color, border: 'none' }
  }, () => info.label)
}

const columns = [
  {
    title: '时间',
    key: 'created_at',
    width: 180,
    render: (row: any) => new Date(row.created_at).toLocaleString('zh-CN'),
  },
  {
    title: '类型',
    key: 'type',
    width: 100,
    render: (row: any) => getTypeTag(row.type),
  },
  {
    title: '金额',
    key: 'amount',
    width: 150,
    render: (row: any) => {
      const amount = parseFloat(row.amount)
      const sign = amount >= 0 ? '+' : ''
      const color = amount >= 0 ? '#22c55e' : '#ef4444'
      return h('span', { style: { color, fontWeight: 500 } }, sign + amount.toFixed(2))
    },
  },
  {
    title: '余额',
    key: 'balance_after',
    width: 150,
    render: (row: any) => parseFloat(row.balance_after).toFixed(2) + ' USDT',
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
  await fetchTransactions()
})
</script>

<template>
  <MainLayout>
    <div class="wallet-page">
      <!-- Toast Message -->
      <Transition name="toast">
        <div 
          v-if="showStatus" 
          class="toast-message"
          :class="statusType"
        >
          {{ statusMessage }}
        </div>
      </Transition>
      
      <!-- Header -->
      <div class="page-header">
        <h1>钱包管理</h1>
        <NSpace>
          <NButton type="primary" @click="showDepositModal = true">
            充值
          </NButton>
          <NButton 
            type="warning" 
            secondary 
            @click="handleReset"
            :loading="resetLoading"
          >
            重置账户
          </NButton>
        </NSpace>
      </div>
      
      <!-- Balance Cards -->
      <NGrid :cols="4" :x-gap="16" :y-gap="16" class="balance-grid">
        <NGi>
          <NCard class="stat-card">
            <NStatistic label="可用余额" :value="walletStore.formattedBalance">
              <template #suffix>
                <span class="currency">USDT</span>
              </template>
            </NStatistic>
          </NCard>
        </NGi>
        <NGi>
          <NCard class="stat-card">
            <NStatistic label="冻结保证金" :value="walletStore.frozen.toFixed(2)">
              <template #suffix>
                <span class="currency">USDT</span>
              </template>
            </NStatistic>
          </NCard>
        </NGi>
        <NGi>
          <NCard class="stat-card">
            <NStatistic label="总权益" :value="walletStore.formattedEquity">
              <template #suffix>
                <span class="currency">USDT</span>
              </template>
            </NStatistic>
          </NCard>
        </NGi>
        <NGi>
          <NCard class="stat-card pnl-card">
            <NStatistic 
              label="累计盈亏" 
              :value="walletStore.formattedPnl"
              :value-style="{ color: pnlColor }"
            >
              <template #suffix>
                <span class="currency" :style="{ color: pnlColor }">USDT</span>
              </template>
            </NStatistic>
          </NCard>
        </NGi>
      </NGrid>
      
      <!-- Transactions Table -->
      <NCard title="资金流水" class="transactions-card">
        <template #header-extra>
          <NButton size="small" quaternary @click="fetchTransactions" :loading="loading">
            刷新
          </NButton>
        </template>
        
        <NDataTable
          v-if="transactions.length > 0"
          :columns="columns"
          :data="transactions"
          :row-key="(row: any) => row.id"
          size="small"
          :bordered="false"
          :theme-overrides="{
            thColor: '#18181b',
            tdColor: 'transparent',
            thTextColor: '#9ca3af',
            tdTextColor: '#e5e7eb',
            borderColor: 'rgba(255,255,255,0.05)',
          }"
        />
        
        <NEmpty v-else description="暂无流水记录" />
      </NCard>
      
      <!-- Deposit Modal -->
      <NModal v-model:show="showDepositModal" preset="card" title="充值" style="max-width: 400px;">
        <div class="deposit-form">
          <p style="color: #9ca3af; margin-bottom: 16px;">
            输入充值金额 (模拟资金)
          </p>
          <NInputNumber
            v-model:value="depositAmount"
            :min="1"
            :max="1000000"
            placeholder="输入金额"
            style="width: 100%;"
          >
            <template #suffix>USDT</template>
          </NInputNumber>
          
          <div class="quick-amounts">
            <NButton size="small" quaternary @click="depositAmount = 1000">1,000</NButton>
            <NButton size="small" quaternary @click="depositAmount = 5000">5,000</NButton>
            <NButton size="small" quaternary @click="depositAmount = 10000">10,000</NButton>
            <NButton size="small" quaternary @click="depositAmount = 50000">50,000</NButton>
          </div>
          
          <NButton 
            type="primary" 
            block 
            @click="handleDeposit"
            :loading="depositLoading"
            style="margin-top: 24px;"
          >
            确认充值
          </NButton>
        </div>
      </NModal>
    </div>
  </MainLayout>
</template>

<style scoped>
.wallet-page {
  padding: 24px;
  max-width: 1400px;
  margin: 0 auto;
  position: relative;
}

.toast-message {
  position: fixed;
  top: 24px;
  left: 50%;
  transform: translateX(-50%);
  padding: 12px 24px;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 500;
  z-index: 9999;
  box-shadow: 0 4px 12px rgba(0,0,0,0.3);
}

.toast-message.success {
  background: #22c55e;
  color: white;
}

.toast-message.error {
  background: #ef4444;
  color: white;
}

.toast-message.warning {
  background: #f59e0b;
  color: white;
}

.toast-enter-active,
.toast-leave-active {
  transition: all 0.3s ease;
}

.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateX(-50%) translateY(-20px);
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
}

.page-header h1 {
  font-size: 24px;
  font-weight: 600;
  color: #f5f5f5;
  margin: 0;
}

.balance-grid {
  margin-bottom: 24px;
}

.stat-card {
  background: linear-gradient(135deg, #18181b 0%, #0e0e10 100%);
  border: 1px solid rgba(255,255,255,0.05);
  border-radius: 12px;
}

.stat-card :deep(.n-statistic-value) {
  font-size: 28px;
  font-weight: 700;
}

.currency {
  font-size: 14px;
  color: #6b7280;
  margin-left: 4px;
}

.transactions-card {
  background: #18181b;
  border: 1px solid rgba(255,255,255,0.05);
  border-radius: 12px;
}

.quick-amounts {
  display: flex;
  gap: 8px;
  margin-top: 12px;
}

.deposit-form {
  padding: 8px 0;
}
</style>
