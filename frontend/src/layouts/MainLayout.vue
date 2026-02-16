<script setup lang="ts">
import { onMounted, computed, type Component } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { NIcon, NTooltip } from 'naive-ui'
import { 
  SpeedometerOutline, 
  HardwareChipOutline, 
  WalletOutline, 
  SettingsOutline,
  ChevronDownOutline,
  NotificationsOutline,
  LogOutOutline,
  AnalyticsOutline,
  ChatboxEllipsesOutline,
  BookOutline,

} from '@vicons/ionicons5'
import { useAuthStore } from '@/stores/auth'
import { useWalletStore } from '@/stores/wallet'
import AccountMenu from '@/components/AccountMenu.vue'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const walletStore = useWalletStore()

// Navigation items with icons and routes
const navItems = [
  { key: 'dashboard', label: 'Dashboard', icon: SpeedometerOutline, route: '/' },
  { key: 'signal', label: 'AI 信号助手', icon: HardwareChipOutline, route: '/signal' },
  { key: 'strategy', label: '量化策略', icon: AnalyticsOutline, route: '/strategy' },
  { key: 'chat', label: 'AI Agent', icon: ChatboxEllipsesOutline, route: '/chat' },
  { key: 'journal', label: '交易日志', icon: BookOutline, route: '/journal' },

  { key: 'wallet', label: '钱包', icon: WalletOutline, route: '/wallet' },
  { key: 'settings', label: 'Settings', icon: SettingsOutline, route: '/settings' },
]

// Current active nav item
const activeNavKey = computed(() => {
  const path = route.path
  if (path === '/signal') return 'signal'
  if (path === '/strategy') return 'strategy'
  if (path === '/chat') return 'chat'
  if (path === '/journal') return 'journal'

  if (path === '/settings') return 'settings'
  if (path === '/wallet') return 'wallet'
  return 'dashboard'
})

// Navigate to route
function handleNav(item: typeof navItems[0]) {
  router.push(item.route)
}

// 🔍 调试: 组件挂载时加载钱包数据
onMounted(async () => {

  await walletStore.fetchBalance()

})

// Handle logout
function handleLogout() {

  authStore.logout()
  walletStore.reset()
  router.push('/login')
}
</script>

<template>
  <div class="flex h-screen" style="background: #0b0b0f;">
    <!-- Sidebar -->
    <aside 
      class="flex flex-col w-16 py-4"
      style="background: #0b0b0f; border-right: 1px solid rgba(255,255,255,0.05);"
    >
      <!-- Logo -->
      <div class="flex items-center justify-center mb-8">
        <div 
          class="w-9 h-9 rounded-lg flex items-center justify-center"
          style="background: linear-gradient(135deg, #8a2be2 0%, #5a189a 100%);"
        >
          <span class="text-white font-bold text-sm">AT</span>
        </div>
      </div>
      
      <!-- Navigation Icons -->
      <nav class="flex-1 flex flex-col items-center gap-1">
        <NTooltip 
          v-for="item in navItems" 
          :key="item.key"
          placement="right"
          :show-arrow="false"
        >
          <template #trigger>
            <button
              @click="handleNav(item)"
              class="w-10 h-10 rounded-lg flex items-center justify-center transition-all duration-150"
              :style="{
                background: activeNavKey === item.key ? 'rgba(138, 43, 226, 0.15)' : 'transparent',
                color: activeNavKey === item.key ? '#a855f7' : '#6b7280',
              }"
            >
              <NIcon size="20">
                <component :is="item.icon" />
              </NIcon>
            </button>
          </template>
          <span class="text-xs">{{ item.label }}</span>
        </NTooltip>
      </nav>
      
      <!-- Bottom: Logout -->
      <div class="flex flex-col items-center gap-2 mt-auto">
        <NTooltip placement="right" :show-arrow="false">
          <template #trigger>
            <button 
              @click="handleLogout"
              class="w-10 h-10 rounded-lg flex items-center justify-center transition-colors hover:bg-red-500/10"
              style="color: #6b7280;"
            >
              <NIcon size="20">
                <LogOutOutline />
              </NIcon>
            </button>
          </template>
          <span class="text-xs">Logout</span>
        </NTooltip>
      </div>
    </aside>
    
    <!-- Main Content -->
    <div class="flex-1 flex flex-col overflow-hidden">
      <!-- Header -->
      <header 
        class="flex items-center justify-between px-6 h-14"
        style="background: transparent; border-bottom: 1px solid rgba(255,255,255,0.05);"
      >
        <!-- Left: Logo & Equity -->
        <div class="flex items-center gap-8">
          <!-- Logo Text -->
          <div class="flex items-center gap-2">
            <div class="w-2 h-2 rounded-full" style="background: #8a2be2;"></div>
            <span class="text-white font-semibold tracking-tight">AutoTrade</span>
          </div>
          
          <!-- Divider -->
          <div class="w-px h-6" style="background: rgba(255,255,255,0.1);"></div>
          
          <!-- Total Equity (Real Data from Store) -->
          <div class="flex items-center gap-6">
            <div>
              <div class="text-xs text-gray-500">Total Equity</div>
              <div class="text-lg font-semibold font-mono text-white">
                {{ walletStore.formattedEquity }} USDT
              </div>
            </div>
            
            <!-- Realized PnL (历史累计已实现盈亏) -->
            <div>
              <div class="text-xs text-gray-500">已实现盈亏</div>
              <div class="flex items-center gap-2">
                <span 
                  class="font-mono text-sm"
                  :style="{ color: walletStore.isPnlPositive ? '#22c55e' : '#ef4444' }"
                >
                  {{ walletStore.formattedPnl }} USDT
                </span>
                <span 
                  class="text-xs px-1.5 py-0.5 rounded font-mono"
                  :style="{ 
                    background: walletStore.isPnlPositive ? 'rgba(34, 197, 94, 0.1)' : 'rgba(239, 68, 68, 0.1)',
                    color: walletStore.isPnlPositive ? '#22c55e' : '#ef4444',
                  }"
                >
                  {{ walletStore.pnlPercent }}
                </span>
              </div>
            </div>
            
            <!-- Available Balance (Real Data from Store) -->
            <div>
              <div class="text-xs text-gray-500">可用余额</div>
              <div class="font-mono text-sm text-gray-300">
                {{ walletStore.formattedBalance }} USDT
              </div>
            </div>
          </div>
        </div>
        
        <!-- Right: Status & User -->
        <div class="flex items-center gap-4">
          <!-- Connection Status -->
          <div class="flex items-center gap-2">
            <span class="relative flex h-1.5 w-1.5">
              <span class="animate-ping absolute inline-flex h-full w-full rounded-full opacity-75" style="background: #22c55e;"></span>
              <span class="relative inline-flex rounded-full h-1.5 w-1.5" style="background: #22c55e;"></span>
            </span>
            <span class="text-xs text-gray-500">Connected</span>
          </div>
          
          <!-- Network Selector -->
          <button 
            class="px-3 py-1.5 rounded-md text-xs flex items-center gap-2 transition-colors"
            style="background: rgba(255,255,255,0.03); color: #9ca3af; border: 1px solid rgba(255,255,255,0.05);"
          >
            <span class="w-1.5 h-1.5 rounded-full" style="background: #f7931a;"></span>
            Mainnet
            <NIcon size="12" style="color: #6b7280;">
              <ChevronDownOutline />
            </NIcon>
          </button>
          
          <!-- Notifications -->
          <button 
            class="w-8 h-8 rounded-md flex items-center justify-center transition-colors"
            style="color: #6b7280;"
          >
            <NIcon size="18">
              <NotificationsOutline />
            </NIcon>
          </button>
          
          <!-- Account Menu -->
          <AccountMenu />
        </div>
      </header>
      
      <!-- Page Content -->
      <main class="flex-1 overflow-auto p-4" style="background: #0b0b0f;">
        <slot />
      </main>
    </div>
  </div>
</template>

<style scoped>
/* Subtle scrollbar */
main::-webkit-scrollbar {
  width: 4px;
}

main::-webkit-scrollbar-track {
  background: transparent;
}

main::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.1);
  border-radius: 2px;
}

main::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.2);
}
</style>
