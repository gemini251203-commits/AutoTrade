<script setup lang="ts">
import { onMounted, onUnmounted, computed, type Component } from 'vue'
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
  NewspaperOutline,
  ShieldCheckmarkOutline,
  GitNetworkOutline,
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
  { key: 'news', label: '新闻', icon: NewspaperOutline, route: '/news' },
  { key: 'hub', label: 'AI Hub', icon: GitNetworkOutline, route: '/hub' },

  { key: 'wallet', label: '钱包', icon: WalletOutline, route: '/wallet' },
  { key: 'risk-config', label: '风控', icon: ShieldCheckmarkOutline, route: '/risk-config' },
  { key: 'settings', label: 'Settings', icon: SettingsOutline, route: '/settings' },
]

// Current active nav item
const activeNavKey = computed(() => {
  const path = route.path
  if (path === '/signal') return 'signal'
  if (path === '/strategy') return 'strategy'
  if (path === '/chat') return 'chat'
  if (path === '/journal') return 'journal'
  if (path === '/news') return 'news'
  if (path === '/hub') return 'hub'
  if (path === '/settings') return 'settings'
  if (path === '/wallet') return 'wallet'
  if (path === '/risk-config') return 'risk-config'
  return 'dashboard'
})

// Mobile Nav Items (all items)
const mobileNavItems = computed(() => navItems)

// Navigate to route
function handleNav(item: typeof navItems[0]) {
  router.push(item.route)
}

// 调试: 组件挂载时加载钱包数据 + 定时轮询
let walletTimer: ReturnType<typeof setInterval> | null = null

onMounted(async () => {
  await walletStore.fetchBalance()
  // 每 3 秒刷新一次余额 (包括 Unrealized PnL)
  walletTimer = setInterval(() => {
    walletStore.fetchBalance()
  }, 10000)
})

onUnmounted(() => {
  if (walletTimer) {
    clearInterval(walletTimer)
    walletTimer = null
  }
})

// Handle logout
function handleLogout() {
  authStore.logout()
  walletStore.reset()
  router.push('/login')
}
</script>

<template>
  <div class="flex h-screen overflow-hidden bg-black text-white selection:bg-purple-500/30">
    <!-- Background Gradient Mesh -->
    <div class="absolute inset-0 z-0 pointer-events-none overflow-hidden">
      <div class="absolute top-[-10%] left-[-10%] w-[40%] h-[40%] rounded-full bg-purple-900/20 blur-[120px]"></div>
      <div class="absolute bottom-[-10%] right-[-10%] w-[40%] h-[40%] rounded-full bg-blue-900/10 blur-[120px]"></div>
    </div>
    
    <!-- Sidebar (Desktop Only) -->
    <aside 
      class="hidden md:flex group relative z-20 flex-col w-20 py-6 items-center border-r border-white/5 bg-black/40 backdrop-blur-xl transition-all duration-300 overflow-hidden"
    >
      <!-- Logo -->
      <div class="mb-10 w-10 h-10 rounded-xl flex items-center justify-center bg-gradient-to-br from-[#8a2be2] to-[#6d28d9] shadow-[0_0_15px_rgba(138,43,226,0.5)]">
        <span class="font-bold text-white text-sm">AT</span>
      </div>
      
      <!-- Nagivation -->
      <nav class="flex-1 flex flex-col items-center gap-3 w-full px-2 overflow-y-auto no-scrollbar py-2">
        <NTooltip 
          v-for="item in navItems" 
          :key="item.key"
          placement="right"
          :show-arrow="false"
          trigger="hover"
        >
          <template #trigger>
            <button
              @click="handleNav(item)"
              class="group/btn relative w-12 h-12 rounded-xl flex items-center justify-center transition-all duration-300 mx-auto"
              :class="activeNavKey === item.key ? 'bg-white/10 text-purple-400' : 'text-gray-500 hover:text-gray-200 hover:bg-white/5'"
            >
              <!-- Active Indicator Line -->
              <div 
                v-if="activeNavKey === item.key"
                class="absolute left-0 top-1/2 -translate-y-1/2 w-1 h-6 bg-purple-500 rounded-r-full shadow-[0_0_10px_#a855f7]"
              ></div>
              
              <!-- Icon -->
              <NIcon size="22" class="transition-transform group-hover/btn:scale-110 group-active/btn:scale-95 flex-shrink-0">
                <component :is="item.icon" />
              </NIcon>

              <!-- Label (removed expansion logic, kept invisible or removed) -->
            </button>
          </template>
          <span class="font-medium">{{ item.label }}</span>
        </NTooltip>
      </nav>
      
      <!-- Bottom Actions -->
      <div class="mt-auto flex flex-col gap-4 mb-2">
        <div class="w-8 h-[1px] bg-white/10 mx-auto"></div>
        <NTooltip placement="right" :show-arrow="false">
          <template #trigger>
            <button 
              @click="handleLogout"
              class="w-12 h-12 rounded-xl flex items-center justify-center text-gray-500 hover:text-red-400 hover:bg-red-500/10 transition-all"
            >
              <NIcon size="22">
                <LogOutOutline />
              </NIcon>
            </button>
          </template>
          <span>退出登录</span>
        </NTooltip>
      </div>
    </aside>
    
    <!-- Main Area -->
    <div class="relative z-10 flex-1 flex flex-col h-full bg-transparent">
      <!-- Header -->
      <header 
        class="relative z-50 h-16 px-3 md:px-8 flex items-center justify-between border-b border-white/5 bg-black/20 backdrop-blur-md"
      >
        <!-- Left: Branding & Equity -->
        <div class="flex items-center gap-6">
          <!-- Desktop: Full Stats -->
          <div class="hidden md:flex items-center gap-6">
            <div class="flex flex-col">
              <span class="text-xs text-gray-500 uppercase tracking-wider font-semibold">Total Equity</span>
              <div class="text-xl font-bold font-mono text-white tracking-tight flex items-baseline gap-2">
                {{ walletStore.formattedEquity }} <span class="text-sm text-gray-400 font-normal">USDT</span>
              </div>
            </div>
            
            <div class="h-8 w-[1px] bg-white/10"></div>
            
            <div class="flex flex-col">
              <span class="text-xs text-gray-500 uppercase tracking-wider font-semibold">Realized PnL</span>
              <div class="flex items-center gap-2">
                <span 
                  class="font-mono font-medium transition-colors duration-500"
                  :class="walletStore.isPnlPositive ? 'text-[#00e676]' : 'text-[#ff1744]'"
                >
                  {{ walletStore.formattedPnl }}
                </span>
                <span 
                  class="text-xs px-1.5 rounded font-mono font-bold"
                  :class="walletStore.isPnlPositive ? 'bg-[#00e676]/10 text-[#00e676]' : 'bg-[#ff1744]/10 text-[#ff1744]'"
                >
                  {{ walletStore.pnlPercent }}
                </span>
              </div>
            </div>
            
            <div class="h-8 w-[1px] bg-white/10"></div>
            
            <div class="flex flex-col">
              <span class="text-xs text-gray-500 uppercase tracking-wider font-semibold">Unrealized PnL</span>
              <div class="flex items-center gap-2">
                <span 
                  class="font-mono font-medium transition-colors duration-500"
                  :class="walletStore.isUnrealizedPnlPositive ? 'text-[#00e676]' : 'text-[#ff1744]'"
                >
                  {{ walletStore.formattedUnrealizedPnl }}
                </span>
                <span class="text-xs text-gray-400 font-normal">USDT</span>
              </div>
            </div>
          </div>

          <!-- Mobile: Simplified Equity Only -->
          <div class="flex md:hidden flex-col">
             <div class="flex items-center gap-2">
                <div class="w-6 h-6 rounded-md bg-gradient-to-br from-[#8a2be2] to-[#6d28d9] flex items-center justify-center shadow-sm">
                  <span class="font-bold text-white text-[10px]">AT</span>
                </div>
                <span class="font-bold font-mono text-white">{{ walletStore.formattedEquity }}</span>
             </div>
             <div class="flex items-center gap-2 text-[10px] text-gray-400">
                <span>PnL:</span>
                <span :class="walletStore.isPnlPositive ? 'text-[#00e676]' : 'text-[#ff1744]'">
                  {{ walletStore.pnlPercent }}
                </span>
             </div>
          </div>
        </div>
        
        <!-- Right: Status -->
        <div class="flex items-center gap-5">
           <!-- Network Status -->
           <div class="flex items-center gap-2 px-3 py-1.5 rounded-full bg-white/5 border border-white/5">
             <div class="relative flex h-2 w-2">
               <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75 duration-1000"></span>
               <span class="relative inline-flex rounded-full h-2 w-2 bg-green-500 shadow-[0_0_8px_#22c55e]"></span>
             </div>
             <span class="text-xs font-medium text-gray-300">Live Connection</span>
           </div>

           <div class="h-6 w-[1px] bg-white/10"></div>
           
           <!-- Account -->
           <AccountMenu />
        </div>
      </header>
      
      <!-- Route Content -->
      <main class="flex-1 overflow-auto p-3 md:p-6 scroll-smooth pb-24 md:pb-6 mobile-safe-pb">
        <slot />
      </main>
    </div>

    <!-- Mobile Bottom Navigation -->
    <nav class="md:hidden fixed bottom-0 left-0 right-0 z-[90] bg-[#0a0a0f]/90 backdrop-blur-xl border-t border-white/10 flex items-center overflow-x-auto no-scrollbar px-1 pb-[env(safe-area-inset-bottom)]">
      <button 
        v-for="item in mobileNavItems" 
        :key="item.key"
        @click="handleNav(item)"
        class="flex flex-col items-center justify-center flex-shrink-0 min-w-[56px] py-2 transition-all active:scale-95"
        :class="activeNavKey === item.key ? 'text-purple-400' : 'text-gray-500'"
      >
        <div 
          class="p-1 rounded-xl transition-colors"
          :class="activeNavKey === item.key ? 'bg-purple-500/10' : ''"
        >
          <NIcon size="20"><component :is="item.icon" /></NIcon>
        </div>
        <span class="text-[9px] mt-0.5 font-medium whitespace-nowrap">{{ item.label }}</span>
      </button>
    </nav>
  </div>
</template>

<style scoped>
/* Scoped Scrollbar */
main::-webkit-scrollbar {
  width: 6px;
}
main::-webkit-scrollbar-track {
  background: transparent;
}
main::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.1);
  border-radius: 99px;
}
main::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.2);
}
</style>
