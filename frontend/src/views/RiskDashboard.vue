<script setup lang="ts">
/**
 * Risk Dashboard — 老板风控控制台
 * ================================
 * 可视化编辑 risk_config.yaml，实时生效
 */
import { ref, onMounted, computed } from 'vue'
import {
  NCard, NButton, NIcon, NInputNumber, NSpin, NAlert, NTag,
  NSpace, NDivider, NSwitch, NDynamicTags, useMessage, NTooltip,
  NGrid, NGi, NResult,
} from 'naive-ui'
import {
  ShieldCheckmarkOutline, SaveOutline, RefreshOutline,
  FlashOutline, WarningOutline, LockClosedOutline,
  TrendingUpOutline, SwapVerticalOutline, BanOutline,
} from '@vicons/ionicons5'
import MainLayout from '@/layouts/MainLayout.vue'
import { getRiskConfig, updateRiskConfig } from '@/api/riskConfig'
import type { RiskConfigResponse } from '@/api/riskConfig'

const message = useMessage()

// State
const loading = ref(true)
const saving = ref(false)
const config = ref<RiskConfigResponse | null>(null)
const hasChanges = ref(false)

// Editable form
const form = ref({
  max_leverage: 20,
  max_daily_loss_pct: 10.0,
  risk_percent: 10.0,
  default_leverage: 5,
  max_positions: 5,
  default_sl_pct: 2.0,
  default_tp_pct: 4.0,
  kelly_fraction: 0.5,
  max_risk_percent: 25.0,
  blacklist: [] as string[],
})

// Load config
async function loadConfig() {
  loading.value = true
  try {
    const data = await getRiskConfig()
    config.value = data
    form.value = { ...data }
    hasChanges.value = false
  } catch (e: any) {
    message.error('加载配置失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    loading.value = false
  }
}

// Save config
async function saveConfig() {
  saving.value = true
  try {
    const data = await updateRiskConfig(form.value)
    config.value = data
    form.value = { ...data }
    hasChanges.value = false
    message.success('✅ 风控配置已保存，下次下单立即生效')
  } catch (e: any) {
    message.error('保存失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    saving.value = false
  }
}

// Track changes
function markChanged() {
  hasChanges.value = true
}

onMounted(loadConfig)
</script>

<template>
  <MainLayout>
    <div class="risk-dashboard">
      <!-- Header -->
      <div class="page-header">
        <div class="header-left">
          <div class="header-icon">
            <NIcon :size="28" color="#f59e0b">
              <ShieldCheckmarkOutline />
            </NIcon>
          </div>
          <div>
            <h1 class="page-title">风控控制台</h1>
            <p class="page-subtitle">实时调整风控参数，保存后立即生效，无需重启系统</p>
          </div>
        </div>
        <div class="header-actions">
          <NButton
            quaternary
            circle
            :loading="loading"
            @click="loadConfig"
          >
            <template #icon>
              <NIcon><RefreshOutline /></NIcon>
            </template>
          </NButton>
          <NButton
            type="warning"
            :loading="saving"
            :disabled="!hasChanges"
            @click="saveConfig"
            strong
          >
            <template #icon>
              <NIcon><SaveOutline /></NIcon>
            </template>
            保存配置
          </NButton>
        </div>
      </div>

      <NSpin :show="loading">
        <div v-if="config" class="config-grid">

          <!-- Section 1: 账户防爆 -->
          <NCard class="config-section section-danger" :bordered="false">
            <template #header>
              <div class="section-header">
                <NIcon :size="20" color="#ef4444"><WarningOutline /></NIcon>
                <span>账户级防爆</span>
                <NTag type="error" size="small" round>最高优先级</NTag>
              </div>
            </template>

            <div class="param-grid">
              <div class="param-item">
                <div class="param-label">
                  <span class="param-name">最大杠杆</span>
                  <span class="param-desc">超过此值的订单将被拒绝</span>
                </div>
                <div class="param-control">
                  <NInputNumber
                    v-model:value="form.max_leverage"
                    :min="1" :max="125" :step="1"
                    size="large"
                    @update:value="markChanged"
                  >
                    <template #suffix>x</template>
                  </NInputNumber>
                </div>
              </div>

              <div class="param-item">
                <div class="param-label">
                  <span class="param-name">日最大亏损</span>
                  <span class="param-desc">达到此比例后自动停止新开仓</span>
                </div>
                <div class="param-control">
                  <NInputNumber
                    v-model:value="form.max_daily_loss_pct"
                    :min="1" :max="100" :step="0.5" :precision="1"
                    size="large"
                    @update:value="markChanged"
                  >
                    <template #suffix>%</template>
                  </NInputNumber>
                </div>
              </div>
            </div>
          </NCard>

          <!-- Section 2: 仓位管理 -->
          <NCard class="config-section section-primary" :bordered="false">
            <template #header>
              <div class="section-header">
                <NIcon :size="20" color="#3b82f6"><TrendingUpOutline /></NIcon>
                <span>仓位管理</span>
                <NTag type="info" size="small" round>每笔交易</NTag>
              </div>
            </template>

            <div class="param-grid">
              <div class="param-item">
                <div class="param-label">
                  <span class="param-name">下单资金比例</span>
                  <span class="param-desc">每次下单使用可用余额的百分比</span>
                </div>
                <div class="param-control">
                  <NInputNumber
                    v-model:value="form.risk_percent"
                    :min="1" :max="100" :step="1" :precision="1"
                    size="large"
                    @update:value="markChanged"
                  >
                    <template #suffix>%</template>
                  </NInputNumber>
                </div>
              </div>

              <div class="param-item">
                <div class="param-label">
                  <span class="param-name">默认杠杆</span>
                  <span class="param-desc">策略未指定杠杆时使用此值</span>
                </div>
                <div class="param-control">
                  <NInputNumber
                    v-model:value="form.default_leverage"
                    :min="1" :max="125" :step="1"
                    size="large"
                    @update:value="markChanged"
                  >
                    <template #suffix>x</template>
                  </NInputNumber>
                </div>
              </div>

              <div class="param-item">
                <div class="param-label">
                  <span class="param-name">最大持仓数</span>
                  <span class="param-desc">同时持有的最大仓位数量</span>
                </div>
                <div class="param-control">
                  <NInputNumber
                    v-model:value="form.max_positions"
                    :min="1" :max="50" :step="1"
                    size="large"
                    @update:value="markChanged"
                  >
                    <template #suffix>个</template>
                  </NInputNumber>
                </div>
              </div>

              <div class="param-item">
                <div class="param-label">
                  <span class="param-name">默认止损</span>
                  <span class="param-desc">策略未指定止损时的默认百分比</span>
                </div>
                <div class="param-control">
                  <NInputNumber
                    v-model:value="form.default_sl_pct"
                    :min="0.1" :max="50" :step="0.5" :precision="1"
                    size="large"
                    @update:value="markChanged"
                  >
                    <template #suffix>%</template>
                  </NInputNumber>
                </div>
              </div>

              <div class="param-item">
                <div class="param-label">
                  <span class="param-name">默认止盈</span>
                  <span class="param-desc">策略未指定止盈时的默认百分比</span>
                </div>
                <div class="param-control">
                  <NInputNumber
                    v-model:value="form.default_tp_pct"
                    :min="0.1" :max="100" :step="0.5" :precision="1"
                    size="large"
                    @update:value="markChanged"
                  >
                    <template #suffix>%</template>
                  </NInputNumber>
                </div>
              </div>
            </div>
          </NCard>

          <!-- Section 3: Kelly 高级 -->
          <NCard class="config-section section-advanced" :bordered="false">
            <template #header>
              <div class="section-header">
                <NIcon :size="20" color="#a855f7"><FlashOutline /></NIcon>
                <span>Kelly 公式 (高级)</span>
                <NTag type="warning" size="small" round>仅 Kelly 模式</NTag>
              </div>
            </template>

            <div class="param-grid">
              <div class="param-item">
                <div class="param-label">
                  <span class="param-name">Kelly 比例</span>
                  <span class="param-desc">0.5 = Half-Kelly（推荐），1.0 = Full-Kelly</span>
                </div>
                <div class="param-control">
                  <NInputNumber
                    v-model:value="form.kelly_fraction"
                    :min="0.1" :max="1.0" :step="0.1" :precision="1"
                    size="large"
                    @update:value="markChanged"
                  />
                </div>
              </div>

              <div class="param-item">
                <div class="param-label">
                  <span class="param-name">单笔最大资金比例</span>
                  <span class="param-desc">Kelly 计算结果的上限</span>
                </div>
                <div class="param-control">
                  <NInputNumber
                    v-model:value="form.max_risk_percent"
                    :min="1" :max="100" :step="1" :precision="1"
                    size="large"
                    @update:value="markChanged"
                  >
                    <template #suffix>%</template>
                  </NInputNumber>
                </div>
              </div>
            </div>
          </NCard>

          <!-- Section 4: 黑名单 -->
          <NCard class="config-section section-blacklist" :bordered="false">
            <template #header>
              <div class="section-header">
                <NIcon :size="20" color="#6b7280"><BanOutline /></NIcon>
                <span>品种黑名单</span>
                <NTag size="small" round>{{ form.blacklist.length }} 个</NTag>
              </div>
            </template>

            <p class="blacklist-hint">
              输入交易对名称（如 DOGEUSDT）后按回车添加，被加入黑名单的品种将被禁止交易
            </p>
            <NDynamicTags
              v-model:value="form.blacklist"
              @update:value="markChanged"
            />
            <div v-if="form.blacklist.length === 0" class="blacklist-empty">
              暂无黑名单品种，所有交易对均可交易
            </div>
          </NCard>

        </div>
      </NSpin>

      <!-- Floating save bar -->
      <Transition name="slide-up">
        <div v-if="hasChanges" class="save-bar">
          <div class="save-bar-content">
            <NIcon :size="18" color="#f59e0b"><WarningOutline /></NIcon>
            <span>有未保存的修改</span>
            <NButton size="small" quaternary @click="loadConfig">放弃修改</NButton>
            <NButton size="small" type="warning" :loading="saving" @click="saveConfig" strong>
              <template #icon><NIcon><SaveOutline /></NIcon></template>
              保存并生效
            </NButton>
          </div>
        </div>
      </Transition>
    </div>
  </MainLayout>
</template>

<style scoped>
.risk-dashboard {
  max-width: 900px;
  margin: 0 auto;
  padding: 0 16px 80px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
  flex-wrap: wrap;
  gap: 12px;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}
.header-icon {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  background: linear-gradient(135deg, rgba(245, 158, 11, 0.15), rgba(245, 158, 11, 0.05));
  display: flex;
  align-items: center;
  justify-content: center;
}
.page-title {
  margin: 0;
  font-size: 22px;
  font-weight: 700;
  color: #e5e7eb;
}
.page-subtitle {
  margin: 2px 0 0;
  font-size: 13px;
  color: #9ca3af;
}
.header-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

.config-grid {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.config-section {
  border-radius: 12px !important;
  background: rgba(30, 30, 40, 0.6) !important;
  backdrop-filter: blur(12px);
  border: 1px solid rgba(255, 255, 255, 0.06) !important;
  transition: border-color 0.2s;
}
.config-section:hover {
  border-color: rgba(255, 255, 255, 0.12) !important;
}

.section-danger {
  border-left: 3px solid #ef4444 !important;
}
.section-primary {
  border-left: 3px solid #3b82f6 !important;
}
.section-advanced {
  border-left: 3px solid #a855f7 !important;
}
.section-blacklist {
  border-left: 3px solid #6b7280 !important;
}

.section-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  font-size: 15px;
}

.param-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 16px;
}
@media (min-width: 640px) {
  .param-grid {
    grid-template-columns: 1fr 1fr;
  }
}

.param-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 12px 14px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.04);
  transition: background 0.15s;
}
.param-item:hover {
  background: rgba(255, 255, 255, 0.06);
}

.param-label {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.param-name {
  font-size: 14px;
  font-weight: 600;
  color: #d1d5db;
}
.param-desc {
  font-size: 12px;
  color: #6b7280;
}
.param-control {
  margin-top: 4px;
}
.param-control :deep(.n-input-number) {
  width: 100%;
}

.blacklist-hint {
  font-size: 13px;
  color: #9ca3af;
  margin: 0 0 12px;
}
.blacklist-empty {
  margin-top: 8px;
  font-size: 13px;
  color: #6b7280;
  font-style: italic;
}

/* Floating save bar */
.save-bar {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  z-index: 100;
  padding: 12px 16px;
  background: rgba(30, 30, 40, 0.95);
  backdrop-filter: blur(12px);
  border-top: 1px solid rgba(245, 158, 11, 0.3);
  box-shadow: 0 -4px 20px rgba(0, 0, 0, 0.3);
}
.save-bar-content {
  max-width: 900px;
  margin: 0 auto;
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 14px;
  color: #f59e0b;
}
.save-bar-content .n-button:last-child {
  margin-left: auto;
}

/* Slide-up animation */
.slide-up-enter-active,
.slide-up-leave-active {
  transition: transform 0.3s ease, opacity 0.3s ease;
}
.slide-up-enter-from,
.slide-up-leave-to {
  transform: translateY(100%);
  opacity: 0;
}
</style>
