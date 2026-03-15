/**
 * Wallet Store
 * =============
 * Pinia store for wallet balance management.
 * 
 * Usage:
 *   import { useWalletStore } from '@/stores/wallet'
 *   const wallet = useWalletStore()
 *   await wallet.fetchBalance()
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import request from '@/utils/request'
import type { WalletAPIResponse } from '@/types/wallet'

// 🔒 类型契约: 使用 WalletAPIResponse 确保字段名与后端一致
// 如果写错字段名 (如 totalEquity 而非 total_equity)，TypeScript 会报错

export const useWalletStore = defineStore('wallet', () => {
  // ============================================
  // State
  // ============================================
  
  const available = ref<number>(0)
  const frozen = ref<number>(0)
  const totalEquity = ref<number>(0)
  const totalPnl = ref<number>(0)
  const unrealizedPnl = ref<number>(0)
  const fundingBalance = ref<number>(0)
  const initialBalance = ref<number>(0)
  const currency = ref<string>('USDT')
  const loading = ref<boolean>(false)
  const error = ref<string | null>(null)
  
  // ============================================
  // Getters
  // ============================================
  
  const formattedBalance = computed(() => {
    return new Intl.NumberFormat('en-US', {
      style: 'decimal',
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(available.value)
  })
  
  const formattedEquity = computed(() => {
    return new Intl.NumberFormat('en-US', {
      style: 'decimal',
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(totalEquity.value)
  })
  
  const formattedPnl = computed(() => {
    // 真实盈亏 = 当前权益 + 未实现盈亏 - 初始投入
    const realPnl = initialBalance.value > 0
      ? (totalEquity.value + unrealizedPnl.value - initialBalance.value)
      : totalPnl.value
    const sign = realPnl >= 0 ? '+' : ''
    return sign + new Intl.NumberFormat('en-US', {
      style: 'decimal',
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(realPnl)
  })
  
  const pnlPercent = computed(() => {
    if (initialBalance.value <= 0) return '+0.00%'
    const realPnl = totalEquity.value + unrealizedPnl.value - initialBalance.value
    const percent = (realPnl / initialBalance.value) * 100
    const sign = percent >= 0 ? '+' : ''
    return sign + percent.toFixed(2) + '%'
  })
  
  const isPnlPositive = computed(() => {
    const realPnl = initialBalance.value > 0
      ? (totalEquity.value + unrealizedPnl.value - initialBalance.value)
      : totalPnl.value
    return realPnl >= 0
  })
  
  const formattedUnrealizedPnl = computed(() => {
    const value = unrealizedPnl.value
    const sign = value >= 0 ? '+' : ''
    return sign + new Intl.NumberFormat('en-US', {
      style: 'decimal',
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(value)
  })
  
  const isUnrealizedPnlPositive = computed(() => unrealizedPnl.value >= 0)
  
  const formattedFundingBalance = computed(() => {
    return new Intl.NumberFormat('en-US', {
      style: 'decimal',
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(fundingBalance.value)
  })
  
  // ============================================
  // Actions
  // ============================================
  
  /**
   * Fetch wallet balance from backend
   * GET /wallet/balance
   */
  async function fetchBalance(): Promise<void> {
    loading.value = true
    error.value = null
    
    try {
      const response = await request.get<WalletAPIResponse>('/wallet/balance')
      
      const data = response.data
      
      // Parse values (backend may return Decimal as string)
      available.value = parseFloat(String(data.available)) || 0
      frozen.value = parseFloat(String(data.frozen)) || 0
      totalEquity.value = parseFloat(String(data.total_equity)) || 0
      totalPnl.value = parseFloat(String(data.total_pnl)) || 0
      unrealizedPnl.value = parseFloat(String(data.unrealized_pnl)) || 0
      fundingBalance.value = parseFloat(String(data.funding_balance)) || 0
      initialBalance.value = parseFloat(String(data.initial_balance)) || 0
      
    } catch (e: any) {
      error.value = e.response?.data?.detail || 'Failed to fetch balance'
    } finally {
      loading.value = false
    }
  }
  
  /**
   * Initialize wallet (for new users)
   * POST /wallet/initialize
   */
  async function initializeWallet(): Promise<void> {
    loading.value = true
    
    try {
      await request.post('/wallet/initialize')
      await fetchBalance()
    } catch (e: any) {
      error.value = e.response?.data?.detail || 'Failed to initialize wallet'
    } finally {
      loading.value = false
    }
  }
  
  /**
   * Reset store state
   */
  function reset(): void {
    available.value = 0
    frozen.value = 0
    totalEquity.value = 0
    totalPnl.value = 0
    unrealizedPnl.value = 0
    fundingBalance.value = 0
    initialBalance.value = 0
    error.value = null
  }
  
  /**
   * Transfer funds between contract and funding accounts
   * POST /wallet/transfer
   */
  async function transferFunds(amount: number, direction: 'to_funding' | 'to_contract'): Promise<{ success: boolean; message: string }> {
    loading.value = true
    error.value = null
    
    try {
      const response = await request.post<{ success: boolean; contract_balance: number; funding_balance: number; message: string }>('/wallet/transfer', {
        amount,
        direction,
      })
      
      // Refresh all balance data
      await fetchBalance()
      
      return { success: true, message: response.data.message }
    } catch (e: any) {
      const msg = e.response?.data?.detail || '划转失败'
      error.value = msg
      return { success: false, message: msg }
    } finally {
      loading.value = false
    }
  }
  
  // ============================================
  // Return
  // ============================================
  
  return {
    // State
    available,
    frozen,
    totalEquity,
    totalPnl,
    unrealizedPnl,
    fundingBalance,
    initialBalance,
    currency,
    loading,
    error,
    
    // Getters
    formattedBalance,
    formattedEquity,
    formattedPnl,
    formattedUnrealizedPnl,
    formattedFundingBalance,
    pnlPercent,
    isPnlPositive,
    isUnrealizedPnlPositive,
    
    // Actions
    fetchBalance,
    initializeWallet,
    transferFunds,
    reset,
  }
})
