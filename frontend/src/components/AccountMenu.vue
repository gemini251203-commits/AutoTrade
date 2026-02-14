<script setup lang="ts">
/**
 * AccountMenu - 账户管理下拉菜单
 * ================================
 * Features:
 * - 显示当前用户信息
 * - 切换已登录账户
 * - 添加新账户
 * - 登出选项
 * - 管理员入口
 */

import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { NIcon, NAvatar, NTag } from 'naive-ui'
import { 
  PersonOutline, 
  PersonAddOutline,
  LogOutOutline,
  SwapHorizontalOutline,
  PeopleOutline,
  ChevronDownOutline,
  CheckmarkOutline,
} from '@vicons/ionicons5'
import { useAuthStore } from '@/stores/auth'
import { useWalletStore } from '@/stores/wallet'

const router = useRouter()
const authStore = useAuthStore()
const walletStore = useWalletStore()

// Menu open state
const isOpen = ref(false)

// Current user
const currentUser = computed(() => authStore.user)
const isAdmin = computed(() => authStore.isAdmin)
const sessions = computed(() => authStore.allSessions)
const activeIndex = computed(() => authStore.activeIndex)

// Toggle menu
function toggleMenu() {
  isOpen.value = !isOpen.value
}

// Close menu
function closeMenu() {
  isOpen.value = false
}

// Switch account
async function handleSwitchAccount(index: number) {
  if (index === activeIndex.value) return
  authStore.switchAccount(index)
  // Refresh wallet data for new account
  await walletStore.fetchBalance()
  closeMenu()
}

// Add account - navigate to login with addAccount flag
function handleAddAccount() {
  closeMenu()
  router.push({ path: '/login', query: { addAccount: 'true' } })
}

// Logout current
async function handleLogoutCurrent() {
  authStore.logoutCurrent()
  walletStore.reset()
  closeMenu()
  
  if (!authStore.isAuthenticated) {
    router.push('/login')
  } else {
    // Refresh wallet for new active account
    await walletStore.fetchBalance()
  }
}

// Logout all
function handleLogoutAll() {
  authStore.logoutAll()
  walletStore.reset()
  closeMenu()
  router.push('/login')
}

// Navigate to admin page
function handleAdminPage() {
  closeMenu()
  router.push('/admin')
}

// Get initials for avatar
function getInitials(username: string): string {
  return username.slice(0, 2).toUpperCase()
}

// Click outside to close
function handleClickOutside(event: MouseEvent) {
  const target = event.target as HTMLElement
  if (!target.closest('.account-menu')) {
    closeMenu()
  }
}

// Add click outside listener
if (typeof window !== 'undefined') {
  document.addEventListener('click', handleClickOutside)
}
</script>

<template>
  <div class="account-menu relative">
    <!-- Trigger Button -->
    <button 
      @click.stop="toggleMenu"
      class="flex items-center gap-2 px-3 py-1.5 rounded-lg transition-all"
      :class="isOpen ? 'bg-white/10' : 'hover:bg-white/5'"
    >
      <NAvatar 
        :size="28" 
        round
        :style="{ 
          background: 'linear-gradient(135deg, #a855f7, #8a2be2)',
          fontSize: '11px',
        }"
      >
        {{ getInitials(authStore.username) }}
      </NAvatar>
      <span class="text-sm text-gray-300">{{ authStore.username }}</span>
      <NIcon size="12" :class="['transition-transform', isOpen ? 'rotate-180' : '']" style="color: #6b7280;">
        <ChevronDownOutline />
      </NIcon>
    </button>

    <!-- Dropdown Menu -->
    <Transition name="dropdown">
      <div 
        v-if="isOpen"
        class="absolute right-0 top-full mt-2 w-72 rounded-xl overflow-hidden z-50"
        style="
          background: #1a1a1f;
          border: 1px solid rgba(255,255,255,0.1);
          box-shadow: 0 10px 40px rgba(0,0,0,0.5);
        "
      >
        <!-- Current User Section -->
        <div class="p-4 border-b border-white/5">
          <div class="flex items-center gap-3">
            <NAvatar 
              :size="44" 
              round
              :style="{ 
                background: 'linear-gradient(135deg, #a855f7, #8a2be2)',
                fontSize: '14px',
              }"
            >
              {{ getInitials(authStore.username) }}
            </NAvatar>
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2">
                <span class="text-white font-medium truncate">{{ currentUser?.username }}</span>
                <NTag v-if="isAdmin" size="tiny" :bordered="false" type="warning">
                  Admin
                </NTag>
              </div>
              <div class="text-xs text-gray-500 truncate">{{ currentUser?.email }}</div>
            </div>
          </div>
        </div>

        <!-- Other Sessions -->
        <div v-if="sessions.length > 1" class="py-2 border-b border-white/5">
          <div class="px-4 py-1 text-xs text-gray-500">切换账户</div>
          <button
            v-for="(session, index) in sessions"
            :key="session.user.id"
            @click="handleSwitchAccount(index)"
            class="w-full flex items-center gap-3 px-4 py-2 hover:bg-white/5 transition-colors"
            :class="index === activeIndex ? 'bg-purple-500/10' : ''"
          >
            <NAvatar 
              :size="32" 
              round
              :style="{ 
                background: index === activeIndex 
                  ? 'linear-gradient(135deg, #a855f7, #8a2be2)' 
                  : '#333',
                fontSize: '11px',
              }"
            >
              {{ getInitials(session.user.username) }}
            </NAvatar>
            <div class="flex-1 min-w-0 text-left">
              <div class="text-sm text-white truncate">{{ session.user.username }}</div>
              <div class="text-xs text-gray-500 truncate">{{ session.user.email }}</div>
            </div>
            <NIcon v-if="index === activeIndex" size="16" style="color: #a855f7;">
              <CheckmarkOutline />
            </NIcon>
          </button>
        </div>

        <!-- Actions -->
        <div class="py-2">
          <!-- Add Account -->
          <button 
            @click="handleAddAccount"
            class="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-white/5 transition-colors text-gray-300"
          >
            <NIcon size="18">
              <PersonAddOutline />
            </NIcon>
            <span class="text-sm">添加账户</span>
          </button>

          <!-- Admin: User Management -->
          <button 
            v-if="isAdmin"
            @click="handleAdminPage"
            class="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-white/5 transition-colors text-gray-300"
          >
            <NIcon size="18">
              <PeopleOutline />
            </NIcon>
            <span class="text-sm">用户管理</span>
          </button>
        </div>

        <!-- Logout Section -->
        <div class="py-2 border-t border-white/5">
          <button 
            @click="handleLogoutCurrent"
            class="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-white/5 transition-colors text-gray-300"
          >
            <NIcon size="18">
              <LogOutOutline />
            </NIcon>
            <span class="text-sm">退出当前账户</span>
          </button>
          
          <button 
            v-if="sessions.length > 1"
            @click="handleLogoutAll"
            class="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-red-500/10 transition-colors text-red-400"
          >
            <NIcon size="18">
              <SwapHorizontalOutline />
            </NIcon>
            <span class="text-sm">退出所有账户</span>
          </button>
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.dropdown-enter-active,
.dropdown-leave-active {
  transition: all 0.2s ease;
}

.dropdown-enter-from,
.dropdown-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}
</style>
