<script setup lang="ts">
import { ref, computed, type Component } from 'vue'
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
  BookOutline,
  NewspaperOutline,
  ShieldCheckmarkOutline,
  GitNetworkOutline,
  DocumentTextOutline,
  EllipsisHorizontalOutline,
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
  { key: 'journal', label: '交易日志', icon: BookOutline, route: '/journal' },
  { key: 'news', label: '新闻', icon: NewspaperOutline, route: '/news' },
  { key: 'hub', label: 'AI Hub', icon: GitNetworkOutline, route: '/hub' },
  { key: 'prompts', label: '提示词', icon: DocumentTextOutline, route: '/prompts' },

  { key: 'wallet', label: '钱包', icon: WalletOutline, route: '/wallet' },
  { key: 'risk-config', label: '风控', icon: ShieldCheckmarkOutline, route: '/risk-config' },
  { key: 'settings', label: '设置', icon: SettingsOutline, route: '/settings' },
]

// Current active nav item
const activeNavKey = computed(() => {
  const path = route.path
  if (path === '/signal') return 'signal'
  if (path === '/strategy') return 'strategy'
  if (path === '/journal') return 'journal'
  if (path === '/news') return 'news'
  if (path === '/hub') return 'hub'
  if (path === '/prompts') return 'prompts'
  if (path === '/settings') return 'settings'
  if (path === '/wallet') return 'wallet'
  if (path === '/risk-config') return 'risk-config'
  return 'dashboard'
})

// ==================== 移动端底部导航 ====================
// 底栏核心 4 项 (高频页面) + "更多" 按钮
const mobileCorePrimaryKeys = ['dashboard', 'hub', 'strategy', 'wallet']
const mobileCoreItems = computed(() => 
  navItems.filter(item => mobileCorePrimaryKeys.includes(item.key))
)
// "更多"面板中的项目
const mobileMoreItems = computed(() => 
  navItems.filter(item => !mobileCorePrimaryKeys.includes(item.key))
)
// "更多"面板打开状态
const showMorePanel = ref(false)
// 当前路由是否在"更多"列表中 → "更多"按钮需高亮
const isMoreActive = computed(() => 
  mobileMoreItems.value.some(item => item.key === activeNavKey.value)
)

// Navigate to route
function handleNav(item: typeof navItems[0]) {
  if (route.path === item.route) return  // already here
  showMorePanel.value = false  // 关闭面板
  router.push(item.route)
}

function handleMoreNav(item: typeof navItems[0]) {
  showMorePanel.value = false
  if (route.path === item.route) return
  router.push(item.route)
}

// 智能轮询: 15 秒间隔，标签页后台自动暂停
import { useVisibilityPolling } from '@/composables/useVisibilityPolling'
useVisibilityPolling(() => walletStore.fetchBalance(), 15000)

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
          :delay="500"
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
    <div class="relative z-10 flex-1 flex flex-col h-full min-w-0 overflow-x-hidden bg-transparent">
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
      <main class="flex-1 overflow-auto max-w-full p-3 md:p-6 scroll-smooth pb-24 md:pb-6 mobile-safe-pb">
        <slot />
      </main>
    </div>

    <!-- Mobile Bottom Navigation (5 items: 4 core + "更多") -->
    <nav class="md:hidden fixed bottom-0 left-0 right-0 z-[90] bg-[#0a0a0f]/95 backdrop-blur-xl border-t border-white/10 flex items-center justify-around px-2 pb-[env(safe-area-inset-bottom)]">
      <!-- Core 4 items -->
      <button 
        v-for="item in mobileCoreItems" 
        :key="item.key"
        @click="handleNav(item)"
        class="flex flex-col items-center justify-center flex-1 py-2.5 transition-all active:scale-95"
        :class="activeNavKey === item.key ? 'text-purple-400' : 'text-gray-500'"
      >
        <div 
          class="p-1.5 rounded-xl transition-colors"
          :class="activeNavKey === item.key ? 'bg-purple-500/10' : ''"
        >
          <NIcon size="22"><component :is="item.icon" /></NIcon>
        </div>
        <span class="text-[10px] mt-0.5 font-medium">{{ item.label }}</span>
      </button>

      <!-- "更多" 按钮 -->
      <button 
        @click="showMorePanel = !showMorePanel"
        class="flex flex-col items-center justify-center flex-1 py-2.5 transition-all active:scale-95"
        :class="isMoreActive || showMorePanel ? 'text-purple-400' : 'text-gray-500'"
      >
        <div 
          class="p-1.5 rounded-xl transition-colors"
          :class="isMoreActive || showMorePanel ? 'bg-purple-500/10' : ''"
        >
          <NIcon size="22"><EllipsisHorizontalOutline /></NIcon>
        </div>
        <span class="text-[10px] mt-0.5 font-medium">更多</span>
      </button>
    </nav>

    <!-- "更多" 弹出面板 -->
    <Transition name="more-overlay">
      <div 
        v-if="showMorePanel" 
        class="md:hidden fixed inset-0 z-[85] bg-black/60 backdrop-blur-sm"
        @click="showMorePanel = false"
      />
    </Transition>
    <Transition name="more-panel">
      <div 
        v-if="showMorePanel" 
        class="md:hidden fixed bottom-[60px] left-0 right-0 z-[88] pb-[env(safe-area-inset-bottom)]"
      >
        <div class="mx-3 mb-2 rounded-2xl bg-[#18181b]/95 backdrop-blur-xl border border-white/10 shadow-[0_-8px_40px_rgba(0,0,0,0.5)] overflow-hidden">
          <div class="grid grid-cols-3 gap-1 p-3">
            <button
              v-for="item in mobileMoreItems"
              :key="item.key"
              @click="handleMoreNav(item)"
              class="flex flex-col items-center gap-1.5 py-3 px-2 rounded-xl transition-all active:scale-95"
              :class="activeNavKey === item.key ? 'bg-purple-500/10 text-purple-400' : 'text-gray-400 hover:bg-white/5'"
            >
              <NIcon size="22"><component :is="item.icon" /></NIcon>
              <span class="text-[11px] font-medium">{{ item.label }}</span>
            </button>
          </div>
        </div>
      </div>
    </Transition>
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

/* "更多" 面板动画 */
.more-panel-enter-active {
  transition: transform 0.25s cubic-bezier(0.16, 1, 0.3, 1), opacity 0.2s ease;
}
.more-panel-leave-active {
  transition: transform 0.2s ease, opacity 0.15s ease;
}
.more-panel-enter-from {
  transform: translateY(100%);
  opacity: 0;
}
.more-panel-leave-to {
  transform: translateY(100%);
  opacity: 0;
}

/* 遮罩动画 */
.more-overlay-enter-active,
.more-overlay-leave-active {
  transition: opacity 0.2s ease;
}
.more-overlay-enter-from,
.more-overlay-leave-to {
  opacity: 0;
}
</style>

