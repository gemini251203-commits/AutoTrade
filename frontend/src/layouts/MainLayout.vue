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
  RocketOutline,
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
  { key: 'autopilot', label: '自动交易', icon: RocketOutline, route: '/autopilot' },
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
  if (path === '/autopilot') return 'autopilot'
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
  <div class="flex h-screen overflow-hidden bg-black text-white selection:bg-purple-500/30">
    <!-- Background Gradient Mesh -->
    <div class="absolute inset-0 z-0 pointer-events-none overflow-hidden">
      <div class="absolute top-[-10%] left-[-10%] w-[40%] h-[40%] rounded-full bg-purple-900/20 blur-[120px]"></div>
      <div class="absolute bottom-[-10%] right-[-10%] w-[40%] h-[40%] rounded-full bg-blue-900/10 blur-[120px]"></div>
    </div>
    
    <!-- Sidebar -->
    <aside 
      class="relative z-20 flex flex-col w-20 py-6 items-center border-r border-white/5 bg-black/40 backdrop-blur-xl transition-all duration-300 hover:w-20"
    >
      <!-- Logo -->
      <div class="mb-10 w-10 h-10 rounded-xl flex items-center justify-center bg-gradient-to-br from-[#8a2be2] to-[#6d28d9] shadow-[0_0_15px_rgba(138,43,226,0.5)]">
        <span class="font-bold text-white text-sm">AT</span>
      </div>
      
      <!-- Nagivation -->
      <nav class="flex-1 flex flex-col items-center gap-3 w-full px-2">
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
              class="group relative w-12 h-12 rounded-xl flex items-center justify-center transition-all duration-300"
              :class="activeNavKey === item.key ? 'bg-white/10 text-purple-400' : 'text-gray-500 hover:text-gray-200 hover:bg-white/5'"
            >
              <!-- Active Indicator Line -->
              <div 
                v-if="activeNavKey === item.key"
                class="absolute left-0 top-1/2 -translate-y-1/2 w-1 h-6 bg-purple-500 rounded-r-full shadow-[0_0_10px_#a855f7]"
              ></div>
              
              <!-- Icon -->
              <NIcon size="22" class="transition-transform group-hover:scale-110 group-active:scale-95">
                <component :is="item.icon" />
              </NIcon>
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
        class="h-16 px-8 flex items-center justify-between border-b border-white/5 bg-black/20 backdrop-blur-md"
      >
        <!-- Left: Branding & Equity -->
        <div class="flex items-center gap-6">
          <div class="flex flex-col">
            <span class="text-xs text-gray-500 uppercase tracking-wider font-semibold">Total Equity</span>
            <div class="text-xl font-bold font-mono text-white tracking-tight flex items-baseline gap-2">
              {{ walletStore.formattedEquity }} <span class="text-sm text-gray-400 font-normal">USDT</span>
            </div>
          </div>
          
          <div class="h-8 w-[1px] bg-white/10"></div>
          
          <!-- PnL -->
          <div class="flex flex-col">
            <span class="text-xs text-gray-500 uppercase tracking-wider font-semibold">Realized PnL</span>
            <div class="flex items-center gap-2">
              <span 
                class="font-mono font-medium"
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
        </div>
        
        <!-- Right: Status -->
        <div class="flex items-center gap-5">
           <!-- Network Status -->
           <div class="flex items-center gap-2 px-3 py-1.5 rounded-full bg-white/5 border border-white/5">
             <div class="relative flex h-2 w-2">
               <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75"></span>
               <span class="relative inline-flex rounded-full h-2 w-2 bg-green-500"></span>
             </div>
             <span class="text-xs font-medium text-gray-300">Live Connection</span>
           </div>

           <div class="h-6 w-[1px] bg-white/10"></div>
           
           <!-- Account -->
           <AccountMenu />
        </div>
      </header>
      
      <!-- Route Content -->
      <main class="flex-1 overflow-auto p-6 scroll-smooth">
        <slot />
      </main>
    </div>
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
