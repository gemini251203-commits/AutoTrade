<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { NIcon, NSpin } from 'naive-ui'
import { LockClosedOutline, PersonOutline, LogInOutline, MailOutline, PersonAddOutline } from '@vicons/ionicons5'
import { useAuthStore } from '@/stores/auth'
import request from '@/utils/request'

const router = useRouter()
const authStore = useAuthStore()

// Mode: login or register
const mode = ref<'login' | 'register'>('login')

const username = ref('')
const email = ref('')
const password = ref('')
const confirmPassword = ref('')
const showError = ref(false)
const errorMessage = ref('')
const loading = ref(false)

const isLogin = computed(() => mode.value === 'login')

function toggleMode() {
  mode.value = mode.value === 'login' ? 'register' : 'login'
  showError.value = false
  errorMessage.value = ''
}

async function handleLogin() {
  showError.value = false
  
  if (!username.value || !password.value) {
    showError.value = true
    errorMessage.value = '请输入用户名和密码'
    return
  }
  
  const success = await authStore.login(username.value, password.value)
  
  if (success) {
    router.push('/')
  } else {
    showError.value = true
    errorMessage.value = authStore.error || '登录失败'
  }
}

async function handleRegister() {
  showError.value = false
  
  if (!username.value || !email.value || !password.value) {
    showError.value = true
    errorMessage.value = '请填写所有必填项'
    return
  }
  
  if (password.value !== confirmPassword.value) {
    showError.value = true
    errorMessage.value = '两次密码输入不一致'
    return
  }
  
  if (password.value.length < 6) {
    showError.value = true
    errorMessage.value = '密码至少6个字符'
    return
  }
  
  loading.value = true
  
  try {
    await request.post('/auth/register', {
      username: username.value,
      email: email.value,
      password: password.value,
    })
    
    // 注册成功后自动登录
    const success = await authStore.login(username.value, password.value)
    if (success) {
      router.push('/')
    }
  } catch (err: any) {
    showError.value = true
    errorMessage.value = err.response?.data?.detail || '注册失败'
  } finally {
    loading.value = false
  }
}

function handleSubmit() {
  if (isLogin.value) {
    handleLogin()
  } else {
    handleRegister()
  }
}

// Handle Enter key
function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter') {
    handleSubmit()
  }
}
</script>

<template>
  <div 
    class="min-h-screen flex items-center justify-center p-4"
    style="background: #0a0a0a;"
  >
    <!-- Background Grid Effect -->
    <div 
      class="absolute inset-0 opacity-[0.03] animate-pulse"
      style="
        background-image: linear-gradient(rgba(138,43,226,0.3) 1px, transparent 1px),
                          linear-gradient(90deg, rgba(138,43,226,0.3) 1px, transparent 1px);
        background-size: 50px 50px;
        animation-duration: 4s;
      "
    ></div>
    
    <!-- Login/Register Card -->
    <div 
      class="relative w-full max-w-md rounded-2xl p-8 glass-panel fade-in slide-up"
      style="
        transition: all 0.5s ease;
      "
    >
      <!-- Logo -->
      <div class="text-center mb-8">
        <div class="flex items-center justify-center gap-2 mb-2">
          <div class="w-3 h-3 rounded-full" style="background: #8a2be2;"></div>
          <span class="text-2xl font-bold text-white tracking-tight">AutoTrade</span>
          <span class="text-xs px-2 py-0.5 rounded" style="background: rgba(138, 43, 226, 0.2); color: #a855f7;">
            PRO
          </span>
        </div>
        <p class="text-sm text-gray-500">{{ isLogin ? 'AI-Powered Trading Terminal' : '创建新账户' }}</p>
      </div>
      
      <!-- Error Message -->
      <div 
        v-if="showError && errorMessage"
        class="mb-6 p-3 rounded-lg text-sm"
        style="background: rgba(220, 38, 38, 0.1); border: 1px solid rgba(220, 38, 38, 0.2); color: #ef4444;"
      >
        {{ errorMessage }}
      </div>
      
      <!-- Form -->
      <div class="space-y-4">
        <!-- Username -->
        <div>
          <label class="block text-xs text-gray-500 mb-2">用户名</label>
          <div 
            class="flex items-center gap-3 rounded-lg px-4 py-3 transition-all"
            style="background: #0f0f14; border: 1px solid rgba(255, 255, 255, 0.1);"
          >
            <NIcon size="18" style="color: #6b7280;">
              <PersonOutline />
            </NIcon>
            <input
              v-model="username"
              type="text"
              placeholder="请输入用户名"
              class="flex-1 bg-transparent text-white text-sm outline-none placeholder:text-gray-600"
              @keydown="handleKeydown"
            />
          </div>
        </div>
        
        <!-- Email (Register only) -->
        <div v-if="!isLogin">
          <label class="block text-xs text-gray-500 mb-2">邮箱</label>
          <div 
            class="flex items-center gap-3 rounded-lg px-4 py-3 transition-all"
            style="background: #0f0f14; border: 1px solid rgba(255, 255, 255, 0.1);"
          >
            <NIcon size="18" style="color: #6b7280;">
              <MailOutline />
            </NIcon>
            <input
              v-model="email"
              type="email"
              placeholder="请输入邮箱"
              class="flex-1 bg-transparent text-white text-sm outline-none placeholder:text-gray-600"
              @keydown="handleKeydown"
            />
          </div>
        </div>
        
        <!-- Password -->
        <div>
          <label class="block text-xs text-gray-500 mb-2">密码</label>
          <div 
            class="flex items-center gap-3 rounded-lg px-4 py-3 transition-all"
            style="background: #0f0f14; border: 1px solid rgba(255, 255, 255, 0.1);"
          >
            <NIcon size="18" style="color: #6b7280;">
              <LockClosedOutline />
            </NIcon>
            <input
              v-model="password"
              type="password"
              placeholder="请输入密码"
              class="flex-1 bg-transparent text-white text-sm outline-none placeholder:text-gray-600"
              @keydown="handleKeydown"
            />
          </div>
        </div>
        
        <!-- Confirm Password (Register only) -->
        <div v-if="!isLogin">
          <label class="block text-xs text-gray-500 mb-2">确认密码</label>
          <div 
            class="flex items-center gap-3 rounded-lg px-4 py-3 transition-all"
            style="background: #0f0f14; border: 1px solid rgba(255, 255, 255, 0.1);"
          >
            <NIcon size="18" style="color: #6b7280;">
              <LockClosedOutline />
            </NIcon>
            <input
              v-model="confirmPassword"
              type="password"
              placeholder="再次输入密码"
              class="flex-1 bg-transparent text-white text-sm outline-none placeholder:text-gray-600"
              @keydown="handleKeydown"
            />
          </div>
        </div>
        
        <!-- Submit Button -->
        <button
          @click="handleSubmit"
          :disabled="authStore.loading || loading"
          class="w-full py-3.5 rounded-lg font-medium text-white flex items-center justify-center gap-2 transition-all mt-6"
          :style="{
            background: (authStore.loading || loading) ? '#5a189a' : 'linear-gradient(135deg, #8a2be2 0%, #5a189a 100%)',
            boxShadow: (authStore.loading || loading) ? 'none' : '0 4px 20px rgba(138, 43, 226, 0.4)',
            cursor: (authStore.loading || loading) ? 'not-allowed' : 'pointer',
          }"
        >
          <NSpin v-if="authStore.loading || loading" size="small" />
          <template v-else>
            <NIcon size="18">
              <component :is="isLogin ? LogInOutline : PersonAddOutline" />
            </NIcon>
            {{ isLogin ? '登录' : '注册账户' }}
          </template>
        </button>
      </div>
      
      <!-- Toggle Mode -->
      <div class="mt-6 text-center">
        <button 
          @click="toggleMode"
          class="text-sm text-gray-500 hover:text-purple-400 transition-colors"
        >
          {{ isLogin ? '没有账户？点击注册' : '已有账户？点击登录' }}
        </button>
      </div>
      
      <!-- Footer -->
      <div v-if="isLogin" class="mt-8 text-center">
        <p class="text-xs text-gray-600">
          默认账户: <span class="text-gray-500">admin / admin</span>
        </p>
      </div>
      
      <!-- Decorative Elements -->
      <div 
        class="absolute -top-20 -right-20 w-40 h-40 rounded-full opacity-20 blur-3xl"
        style="background: #8a2be2;"
      ></div>
      <div 
        class="absolute -bottom-20 -left-20 w-40 h-40 rounded-full opacity-10 blur-3xl"
        style="background: #00d4ff;"
      ></div>
    </div>
    
    <!-- Version -->
    <div class="absolute bottom-4 text-xs font-mono text-gray-700">
      v1.0.0 | Cyberpunk Finance Edition
    </div>
  </div>
</template>

<style scoped>
/* Focus state for inputs */
input:focus {
  outline: none;
}

div:has(> input:focus) {
  border-color: #8a2be2 !important;
}
</style>
