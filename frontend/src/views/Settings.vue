<script setup lang="ts">
/**
 * Settings Page
 * ==============
 * 用户设置页面，包含 AI 配置
 */

import { ref, onMounted, computed } from 'vue'
import MainLayout from '@/layouts/MainLayout.vue'
import {
  NCard,
  NForm,
  NFormItem,
  NInput,
  NButton,
  NSpace,
  NSpin,
  NText,
  NIcon,
  NGrid,
  NGi,
  NCollapse,
  NCollapseItem,
  createDiscreteApi,
  NDivider,
  NTag,
} from 'naive-ui'
import { CloudOutline, LaptopOutline, CheckmarkCircle, AlertCircle } from '@vicons/ionicons5'
import { useRouter } from 'vue-router'
import {
  getAIConfig,
  updateAIConfig,
  testAIConnection,
  type AIConfigResponse,
  type AIProvider,
} from '@/api/aiConfig'

const router = useRouter()
const { message } = createDiscreteApi(['message'])

// ==================== State ====================

const loading = ref(false)
const saving = ref(false)
const testing = ref(false)
const testResult = ref<{ success: boolean; message: string } | null>(null)

// 表单数据 - 保持与后端 UserAIConfig 模型一致
const formData = ref({
  provider: 'ollama' as AIProvider,
  api_base_url: 'https://api.deepseek.com',
  api_key: '',
  api_model: 'deepseek-chat',
  ollama_base_url: 'http://localhost:11434',
  ollama_model: 'deepseek-r1:14b',
  system_prompt: 'You are QuantaPro, a professional Crypto Quant Trader.',
})

// 当前保存的 key 脱敏显示
const savedKeyMasked = ref('')

// 是否使用 Cloud API
const isCloudProvider = computed(() => 
  formData.value.provider === 'deepseek' || formData.value.provider === 'openai'
)

// ==================== Methods ====================

async function loadConfig() {
  loading.value = true
  try {
    const config = await getAIConfig()
    
    // 填充表单
    formData.value.provider = config.provider as AIProvider
    formData.value.api_base_url = config.api_base_url || 'https://api.deepseek.com'
    formData.value.api_model = config.api_model || 'deepseek-chat'
    formData.value.ollama_base_url = config.ollama_base_url || 'http://localhost:11434'
    formData.value.ollama_model = config.ollama_model || 'deepseek-r1:14b'
    // 如果后端返回空，使用默认值
    if (config.system_prompt) {
      formData.value.system_prompt = config.system_prompt
    }
    
    // 保存脱敏后的 key
    savedKeyMasked.value = config.api_key_masked || ''
    
  } catch (error) {
    console.error('Failed to load AI config:', error)
    message.error('加载配置失败')
  } finally {
    loading.value = false
  }
}

async function saveConfig() {
  saving.value = true
  try {
    const updateData: Record<string, unknown> = {
      provider: formData.value.provider,
      system_prompt: formData.value.system_prompt,
    }
    
    if (isCloudProvider.value) {
      updateData.api_base_url = formData.value.api_base_url
      updateData.api_model = formData.value.api_model
      // 只有输入了新 key 才发送
      if (formData.value.api_key.trim()) {
        updateData.api_key = formData.value.api_key.trim()
      }
    } else {
      updateData.ollama_base_url = formData.value.ollama_base_url
      updateData.ollama_model = formData.value.ollama_model
    }
    
    const result = await updateAIConfig(updateData as any)
    savedKeyMasked.value = result.api_key_masked || ''
    formData.value.api_key = '' // 清空输入框
    
    message.success('配置已保存')
  } catch (error) {
    console.error('Failed to save AI config:', error)
    message.error('保存失败')
  } finally {
    saving.value = false
  }
}

async function testConnection() {
  testing.value = true
  testResult.value = null
  
  try {
    const testData = {
      provider: formData.value.provider,
      api_base_url: isCloudProvider.value ? formData.value.api_base_url : undefined,
      api_key: isCloudProvider.value && formData.value.api_key.trim() 
        ? formData.value.api_key.trim() : undefined,
      api_model: isCloudProvider.value ? formData.value.api_model : undefined,
      ollama_base_url: !isCloudProvider.value ? formData.value.ollama_base_url : undefined,
      ollama_model: !isCloudProvider.value ? formData.value.ollama_model : undefined,
    }
    
    const result = await testAIConnection(testData as any)
    testResult.value = result
    
    if (result.success) {
      message.success(result.message)
    } else {
      message.warning(result.message)
    }
  } catch (error) {
    console.error('Test connection failed:', error)
    testResult.value = { success: false, message: '连接测试失败' }
    message.error('连接测试失败')
  } finally {
    testing.value = false
  }
}


// ==================== Lifecycle ====================

onMounted(() => {
  loadConfig()
})
</script>

<template>
  <MainLayout>
  <div class="settings-page">
    <!-- Header -->
    <div class="page-header">
      <h1 class="page-title">设置</h1>
    </div>

    <NSpin :show="loading">
      <div class="settings-content">
        <!-- AI 配置卡片 -->
        <NCard class="settings-card" :bordered="false">
          <template #header>
            <div class="card-header">
              AI 模型配置
              <NTag size="small" type="primary" round class="ml-2">Core</NTag>
            </div>
          </template>
          
          <NForm
            :model="formData"
            label-placement="top"
            label-width="auto"
            size="medium"
          >
            <!-- 提供商选择 (Card Style) -->
            <NFormItem label="AI 提供商">
              <div class="provider-grid">
                <!-- Ollama Card -->
                <div 
                  class="provider-card" 
                  :class="{ active: formData.provider === 'ollama' }"
                  @click="formData.provider = 'ollama'"
                >
                  <div class="provider-icon">
                    <NIcon :component="LaptopOutline" size="24" />
                  </div>
                  <div class="provider-info">
                    <div class="provider-name">Local LLM</div>
                    <div class="provider-desc">Ollama / 本地运行 (免费)</div>
                  </div>
                  <div class="provider-check" v-if="formData.provider === 'ollama'">
                    <NIcon :component="CheckmarkCircle" color="#8a2be2" />
                  </div>
                </div>

                <!-- DeepSeek Card -->
                <div 
                  class="provider-card" 
                  :class="{ active: formData.provider === 'deepseek' }"
                  @click="formData.provider = 'deepseek'"
                >
                  <div class="provider-icon">
                    <NIcon :component="CloudOutline" size="24" />
                  </div>
                  <div class="provider-info">
                    <div class="provider-name">Cloud API</div>
                    <div class="provider-desc">DeepSeek / OpenAI (推荐)</div>
                  </div>
                  <div class="provider-check" v-if="formData.provider === 'deepseek'">
                    <NIcon :component="CheckmarkCircle" color="#8a2be2" />
                  </div>
                </div>
              </div>
            </NFormItem>

            <NDivider />

            <!-- Cloud API 配置 -->
            <div v-show="isCloudProvider" class="config-section">
              <NGrid :cols="2" :x-gap="24">
                <NGi>
                  <NFormItem label="API Base URL">
                    <NInput
                      v-model:value="formData.api_base_url"
                      placeholder="https://api.deepseek.com"
                    />
                  </NFormItem>
                </NGi>
                <NGi>
                  <NFormItem label="模型名称">
                    <NInput
                      v-model:value="formData.api_model"
                      placeholder="deepseek-chat"
                    />
                  </NFormItem>
                </NGi>
                <NGi :span="2">
                  <NFormItem label="API Key">
                    <NInput
                      v-model:value="formData.api_key"
                      type="password"
                      show-password-on="click"
                      :placeholder="savedKeyMasked || '输入 API Key'"
                    />
                    <template #feedback>
                      <NText depth="3" class="text-xs" v-if="savedKeyMasked">
                        <NIcon :component="CheckmarkCircle" color="#22c55e" depth="1" /> 
                        已配置 ({{ savedKeyMasked }})
                      </NText>
                    </template>
                  </NFormItem>
                </NGi>
              </NGrid>
            </div>

            <!-- Ollama 配置 -->
            <div v-show="!isCloudProvider" class="config-section">
               <NGrid :cols="2" :x-gap="24">
                <NGi>
                  <NFormItem label="Ollama URL">
                    <NInput
                      v-model:value="formData.ollama_base_url"
                      placeholder="http://localhost:11434"
                    />
                  </NFormItem>
                </NGi>
                <NGi>
                  <NFormItem label="模型名称">
                    <NInput
                      v-model:value="formData.ollama_model"
                      placeholder="deepseek-r1:14b"
                    />
                  </NFormItem>
                </NGi>
              </NGrid>
            </div>

            <!-- 测试连接 -->
            <div class="test-section">
                <NButton
                  secondary
                  type="info"
                  :loading="testing"
                  @click="testConnection"
                  class="test-btn"
                >
                  <template #icon>
                    <NIcon :component="testing ? undefined : CloudOutline" />
                  </template>
                  测试连接
                </NButton>
                
                <div v-if="testResult" class="test-result" :class="testResult.success ? 'success' : 'error'">
                  <NIcon :component="testResult.success ? CheckmarkCircle : AlertCircle" />
                  <span>{{ testResult.message }}</span>
                </div>
            </div>

            <NDivider />

            <!-- 系统提示词 -->
            <NCollapse arrow-placement="right">
              <NCollapseItem title="高级设置" name="advanced">
                <div class="advanced-section">
                  <NFormItem label="系统提示词 (System Prompt)">
                    <NInput
                      v-model:value="formData.system_prompt"
                      type="textarea"
                      :rows="3"
                      placeholder="You are QuantaPro..."
                      class="prompt-input"
                    />
                  </NFormItem>
                </div>
              </NCollapseItem>
            </NCollapse>

            <!-- 保存按钮 -->
            <div class="actions">
              <NButton
                type="primary"
                size="large"
                :loading="saving"
                @click="saveConfig"
                block
                color="#8a2be2"
              >
                保存配置
              </NButton>
            </div>
          </NForm>
        </NCard>
      </div>
    </NSpin>
  </div>
  </MainLayout>
</template>

<style scoped>
.settings-page {
  min-height: calc(100vh - 56px);
  padding: 24px;
}

.page-header {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 32px;
  max-width: 800px;
  margin-left: auto;
  margin-right: auto;
}

.page-title {
  font-size: 28px;
  font-weight: 700;
  color: #fff;
  margin: 0;
  letter-spacing: -0.5px;
}

.settings-content {
  max-width: 800px;
  margin: 0 auto;
}

.settings-card {
  background: rgba(20, 20, 32, 0.6);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 16px;
  box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.36);
}

.card-header {
  font-size: 18px;
  font-weight: 600;
  display: flex;
  align-items: center;
}

/* Provider Grid */
.provider-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  width: 100%;
}

.provider-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.2s ease;
  position: relative;
  overflow: hidden;
}

.provider-card:hover {
  background: rgba(255, 255, 255, 0.06);
  border-color: rgba(138, 43, 226, 0.3);
}

.provider-card.active {
  background: rgba(138, 43, 226, 0.1);
  border-color: #8a2be2;
}

.provider-icon {
  width: 40px;
  height: 40px;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
}

.provider-card.active .provider-icon {
  background: #8a2be2;
}

.provider-info {
  flex: 1;
}

.provider-name {
  font-weight: 600;
  color: #fff;
  font-size: 14px;
}

.provider-desc {
  font-size: 12px;
  color: #9ca3af;
  margin-top: 2px;
}

.provider-check {
  margin-left: auto;
}

/* Test Section */
.test-section {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-top: 8px;
}

.test-result {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  padding: 6px 12px;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.05);
}

.test-result.success {
  color: #22c55e;
  background: rgba(34, 197, 94, 0.1);
}

.test-result.error {
  color: #ef4444;
  background: rgba(239, 68, 68, 0.1);
}

/* Advanced Section */
.advanced-section {
  padding-top: 8px;
}

.risk-grid {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 16px;
  margin-top: 16px;
}

.actions {
  margin-top: 32px;
}

.ml-2 {
  margin-left: 8px;
}

.text-xs {
  font-size: 12px;
}
</style>
