<script setup lang="ts">
/**
 * Admin Page - 用户管理页面
 * ==========================
 * 管理员可查看和管理所有用户
 */

import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { NIcon, NDataTable, NButton, NTag, NModal, NSpin } from 'naive-ui'
import { 
  ArrowBackOutline, 
  TrashOutline, 
  PersonOutline,
  ShieldCheckmarkOutline,
} from '@vicons/ionicons5'
import { useAuthStore } from '@/stores/auth'
import request from '@/utils/request'

const router = useRouter()
const authStore = useAuthStore()

// State
const loading = ref(true)
const users = ref<any[]>([])
const showDeleteModal = ref(false)
const userToDelete = ref<any>(null)
const deleteLoading = ref(false)

// Check if user is admin
if (!authStore.isAdmin) {
  router.push('/')
}

// Table columns
const columns = [
  {
    title: 'ID',
    key: 'id',
    width: 80,
  },
  {
    title: '用户名',
    key: 'username',
    render: (row: any) => {
      return row.username
    },
  },
  {
    title: '邮箱',
    key: 'email',
  },
  {
    title: '状态',
    key: 'is_active',
    width: 100,
    render: (row: any) => {
      return row.is_active ? '[Active] 激活' : '[Disabled] 禁用'
    },
  },
  {
    title: '角色',
    key: 'is_superuser',
    width: 100,
    render: (row: any) => {
      return row.is_superuser ? '管理员' : '用户'
    },
  },
  {
    title: '操作',
    key: 'actions',
    width: 100,
    render: (row: any) => {
      // Don't show delete for current user
      if (row.id === authStore.user?.id) {
        return '当前用户'
      }
      return null
    },
  },
]

// Fetch all users
async function fetchUsers() {
  loading.value = true
  try {
    const res = await request.get('/admin/users')
    users.value = res.data
  } catch (err: any) {
    console.error('[Admin] Failed to fetch users:', err)
  } finally {
    loading.value = false
  }
}

// Delete user
async function confirmDelete() {
  if (!userToDelete.value) return
  
  deleteLoading.value = true
  try {
    await request.delete(`/admin/users/${userToDelete.value.id}`)
    // Refresh list
    await fetchUsers()
    showDeleteModal.value = false
    userToDelete.value = null
  } catch (err: any) {
    console.error('[Admin] Failed to delete user:', err)
  } finally {
    deleteLoading.value = false
  }
}

// Go back
function goBack() {
  router.push('/')
}

onMounted(() => {
  fetchUsers()
})
</script>

<template>
  <div class="min-h-screen p-8" style="background: #0b0b0f;">
    <!-- Header -->
    <div class="flex items-center gap-4 mb-8">
      <button 
        @click="goBack"
        class="w-10 h-10 rounded-lg flex items-center justify-center hover:bg-white/5 transition-colors"
        style="border: 1px solid rgba(255,255,255,0.1);"
      >
        <NIcon size="20" style="color: #9ca3af;">
          <ArrowBackOutline />
        </NIcon>
      </button>
      
      <div>
        <h1 class="text-2xl font-bold text-white flex items-center gap-2">
          <NIcon size="24" style="color: #a855f7;">
            <ShieldCheckmarkOutline />
          </NIcon>
          用户管理
        </h1>
        <p class="text-sm text-gray-500">管理系统中的所有用户账户</p>
      </div>
    </div>

    <!-- Stats -->
    <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
      <div 
        class="p-4 rounded-xl"
        style="background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.05);"
      >
        <div class="text-gray-500 text-sm mb-1">总用户数</div>
        <div class="text-2xl font-bold text-white">{{ users.length }}</div>
      </div>
      <div 
        class="p-4 rounded-xl"
        style="background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.05);"
      >
        <div class="text-gray-500 text-sm mb-1">管理员</div>
        <div class="text-2xl font-bold text-purple-400">
          {{ users.filter(u => u.is_superuser).length }}
        </div>
      </div>
      <div 
        class="p-4 rounded-xl"
        style="background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.05);"
      >
        <div class="text-gray-500 text-sm mb-1">普通用户</div>
        <div class="text-2xl font-bold text-gray-300">
          {{ users.filter(u => !u.is_superuser).length }}
        </div>
      </div>
    </div>

    <!-- User Table -->
    <div 
      class="rounded-xl overflow-hidden"
      style="background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.05);"
    >
      <div v-if="loading" class="flex items-center justify-center py-20">
        <NSpin size="large" />
      </div>
      <NDataTable 
        v-else
        :columns="columns"
        :data="users"
        :bordered="false"
        size="large"
        :row-class-name="() => 'hover:bg-white/5'"
      />
    </div>
  </div>
</template>

<style scoped>
:deep(.n-data-table-wrapper) {
  background: transparent !important;
}

:deep(.n-data-table-th) {
  background: rgba(255,255,255,0.03) !important;
  color: #9ca3af !important;
  border-bottom: 1px solid rgba(255,255,255,0.05) !important;
}

:deep(.n-data-table-td) {
  background: transparent !important;
  color: #e5e7eb !important;
  border-bottom: 1px solid rgba(255,255,255,0.03) !important;
}

:deep(.n-data-table-tr:hover .n-data-table-td) {
  background: rgba(255,255,255,0.03) !important;
}
</style>
