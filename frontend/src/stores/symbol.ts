/**
 * Symbol Store - 全局交易对状态管理
 * ==================================
 * 
 * 管理当前选中的交易对和价格，供所有组件共享
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

// 支持的交易对列表
export const SYMBOLS = [
  { code: 'BTCUSDT', name: 'BTC/USDT', color: '#f7931a', letter: 'B' },
  { code: 'ETHUSDT', name: 'ETH/USDT', color: '#627eea', letter: 'E' },
  { code: 'BNBUSDT', name: 'BNB/USDT', color: '#f3ba2f', letter: 'B' },
  { code: 'SOLUSDT', name: 'SOL/USDT', color: '#00ffd5', letter: 'S' },
  { code: 'XRPUSDT', name: 'XRP/USDT', color: '#23292f', letter: 'X' },
  { code: 'LTCUSDT', name: 'LTC/USDT', color: '#bfbbbb', letter: 'L' },
  { code: 'DOGEUSDT', name: 'DOGE/USDT', color: '#c2a633', letter: 'D' },
  { code: 'ASTERUSDT', name: 'ASTER/USDT', color: '#e91e63', letter: 'A' },
  { code: 'XAUUSDT', name: 'XAU/USDT', color: '#ffd700', letter: 'G' },
]

export type SymbolCode = typeof SYMBOLS[number]['code']

export interface SymbolInfo {
  code: string
  name: string
  color: string
  letter: string
}

export const useSymbolStore = defineStore('symbol', () => {
  // 当前选中的交易对
  const currentSymbol = ref<string>('BTCUSDT')
  
  // 当前价格
  const currentPrice = ref<number>(0)
  
  // 价格变化百分比
  const priceChangePercent = ref<number>(0)
  
  // 当前交易对信息
  const currentSymbolInfo = computed(() => {
    const found = SYMBOLS.find(s => s.code === currentSymbol.value)
    return found ?? SYMBOLS[0]
  })
  
  // 获取币种基础符号 (如 BTCUSDT -> BTC)
  const baseAsset = computed(() => {
    return currentSymbol.value.replace('USDT', '')
  })
  
  // 设置当前交易对
  function setSymbol(symbol: string) {
    if (currentSymbol.value !== symbol) {

      currentSymbol.value = symbol
      // 重置价格，等待新数据
      currentPrice.value = 0
      priceChangePercent.value = 0
    }
  }
  
  // 更新价格
  function updatePrice(price: number, changePercent?: number) {
    currentPrice.value = price
    if (changePercent !== undefined) {
      priceChangePercent.value = changePercent
    }
  }
  
  // 获取 NSelect 格式的选项列表
  const symbolOptions = computed(() => {
    return SYMBOLS.map(s => ({
      label: s.name,
      value: s.code,
    }))
  })
  
  return {
    // State
    currentSymbol,
    currentPrice,
    priceChangePercent,
    
    // Getters
    currentSymbolInfo,
    baseAsset,
    symbolOptions,
    symbols: SYMBOLS,
    
    // Actions
    setSymbol,
    updatePrice,
  }
})
