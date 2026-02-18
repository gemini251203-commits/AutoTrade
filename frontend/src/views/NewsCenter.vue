<script setup lang="ts">
/**
 * NewsCenter.vue — 新闻中心
 * =========================
 * 实时新闻流 + 情绪仪表盘 + 监控规则管理 + AI思考记录
 */
import { ref, onMounted, computed } from 'vue'
import MainLayout from '@/layouts/MainLayout.vue'
import {
  NCard, NSpace, NTag, NButton, NSelect, NInput,
  NSpin, NEmpty, NGrid, NGridItem, NStatistic,
  NProgress, NModal, NForm, NFormItem, NInputNumber,
  NSwitch, NCollapse, NCollapseItem, NDivider,
  NPopconfirm, NTooltip, NBadge, useMessage,
} from 'naive-ui'
import type { NewsArticle, NewsAlert, NewsThinking, MarketSentiment, TradingStats } from '@/api/news'
import {
  getLatestNews,
  getMarketSentiment,
  getNewsAlerts,
  createNewsAlert,
  updateNewsAlert,
  deleteNewsAlert,
  getNewsThinkings,
  getNewsTradingStats,
} from '@/api/news'

const message = useMessage()

// ==================== 状态 ====================
const loading = ref(false)
const newsList = ref<NewsArticle[]>([])
const alerts = ref<NewsAlert[]>([])
const thinkings = ref<NewsThinking[]>([])
const sentiment = ref<MarketSentiment | null>(null)
const stats = ref<TradingStats | null>(null)

// 筛选
const filterCurrency = ref<string | null>(null)
const filterCategory = ref<string>('')
const filterKeyword = ref('')

// 创建 Alert 弹窗
const showCreateAlert = ref(false)
const alertForm = ref({
  name: '',
  keywords: '',
  currencies: '',
  news_categories: [] as string[],
  sentiment_filter: 'any',
  action: 'notify',
  trade_side: 'buy',
  trade_symbol: 'BTCUSDT',
  trade_position_pct: 10,
  trade_leverage: 5,
  trade_stop_loss_pct: 3,
  trade_take_profit_pct: 9,
})
const alertSaving = ref(false)

// ==================== 分类/情感配置 ====================
const categoryOptions = [
  { value: 'macro', label: '🏛️ 宏观经济' },
  { value: 'etf', label: '📊 ETF/机构' },
  { value: 'regulation', label: '⚖️ 监管政策' },
  { value: 'exchange', label: '🏦 交易所' },
  { value: 'whale', label: '🐳 巨鲸动向' },
  { value: 'project', label: '🔧 项目/技术' },
]
const categoryMap: Record<string, string> = {
  macro: '🏛️ 宏观', etf: '📊 ETF', regulation: '⚖️ 监管',
  exchange: '🏦 交易所', whale: '🐳 巨鲸', project: '🔧 项目',
}
const sentimentColor: Record<string, string> = {
  positive: '#10b981', negative: '#ef4444', neutral: '#6b7280',
}

// ==================== 加载数据 ====================
async function loadAll() {
  loading.value = true
  try {
    await Promise.all([
      loadNews(),
      loadSentiment(),
      loadAlerts(),
      loadThinkings(),
      loadStats(),
    ])
  } finally {
    loading.value = false
  }
}

async function loadNews() {
  try {
    newsList.value = await getLatestNews({
      currency: filterCurrency.value || undefined,
      news_category: filterCategory.value || undefined,
      keyword: filterKeyword.value || undefined,
      limit: 50,
    })
  } catch (e: any) {
    console.error('加载新闻失败', e)
  }
}

async function loadSentiment() {
  try {
    sentiment.value = await getMarketSentiment(filterCurrency.value || 'BTC', 24)
  } catch (e: any) {
    console.error('加载情绪失败', e)
  }
}

async function loadAlerts() {
  try {
    alerts.value = await getNewsAlerts()
  } catch (e: any) {
    console.error('加载监控规则失败', e)
  }
}

async function loadThinkings() {
  try {
    thinkings.value = await getNewsThinkings({ limit: 10 })
  } catch (e: any) {
    console.error('加载思考记录失败', e)
  }
}

async function loadStats() {
  try {
    stats.value = await getNewsTradingStats()
  } catch (e: any) {
    console.error('加载绩效失败', e)
  }
}

// ==================== 监控规则操作 ====================
async function onCreateAlert() {
  if (!alertForm.value.name || !alertForm.value.keywords) {
    message.warning('请填写规则名称和关键词')
    return
  }
  alertSaving.value = true
  try {
    const keywords = alertForm.value.keywords.split(',').map(k => k.trim()).filter(Boolean)
    const currencies = alertForm.value.currencies
      ? alertForm.value.currencies.split(',').map(c => c.trim().toUpperCase()).filter(Boolean)
      : undefined

    await createNewsAlert({
      name: alertForm.value.name,
      keywords,
      currencies,
      news_categories: alertForm.value.news_categories.length > 0
        ? alertForm.value.news_categories : undefined,
      sentiment_filter: alertForm.value.sentiment_filter,
      action: alertForm.value.action,
      ...(alertForm.value.action === 'trade' ? {
        trade_side: alertForm.value.trade_side,
        trade_symbol: alertForm.value.trade_symbol,
        trade_position_pct: alertForm.value.trade_position_pct,
        trade_leverage: alertForm.value.trade_leverage,
        trade_stop_loss_pct: alertForm.value.trade_stop_loss_pct,
        trade_take_profit_pct: alertForm.value.trade_take_profit_pct,
      } : {}),
    })
    message.success('监控规则已创建')
    showCreateAlert.value = false
    await loadAlerts()
  } catch (e: any) {
    message.error(e.response?.data?.detail || '创建失败')
  } finally {
    alertSaving.value = false
  }
}

async function toggleAlert(alert: NewsAlert) {
  try {
    await updateNewsAlert(alert.id, { is_active: !alert.is_active })
    message.success(alert.is_active ? '已暂停' : '已启用')
    await loadAlerts()
  } catch (e: any) {
    message.error('操作失败')
  }
}

async function toggleReliable(alert: NewsAlert) {
  try {
    await updateNewsAlert(alert.id, {
      is_reliable: !alert.is_reliable,
      reliability_note: alert.is_reliable ? '用户标记为不可靠' : '用户重新标记为可靠',
    })
    message.success(alert.is_reliable ? '已标记不可靠' : '已恢复可靠')
    await loadAlerts()
  } catch (e: any) {
    message.error('操作失败')
  }
}

async function onDeleteAlert(id: number) {
  try {
    await deleteNewsAlert(id)
    message.success('已删除')
    await loadAlerts()
  } catch (e: any) {
    message.error('删除失败')
  }
}

// ==================== 辅助 ====================
function formatTime(isoStr: string) {
  if (!isoStr) return '-'
  const d = new Date(isoStr)
  return d.toLocaleString('zh-CN', { hour12: false }).replace(/\//g, '-')
}

function sentimentPercent(s: MarketSentiment | null) {
  if (!s || s.total_articles === 0) return 50
  return Math.round((s.positive_count / s.total_articles) * 100)
}

onMounted(loadAll)
</script>

<template>
  <MainLayout>
    <div class="news-center">
    <!-- 页面标题 -->
    <div class="page-header">
      <h1>📰 新闻中心</h1>
      <p class="subtitle">实时加密货币新闻 · AI 情感分析 · 智能监控</p>
    </div>

    <!-- 顶部统计卡片 -->
    <n-grid :cols="4" :x-gap="16" :y-gap="16" class="stats-grid">
      <n-grid-item>
        <n-card class="stat-card stat-sentiment">
          <n-statistic label="市场情绪" :value="sentiment?.overall === 'positive' ? '看多' : sentiment?.overall === 'negative' ? '看空' : '中性'" />
          <n-progress
            type="line"
            :percentage="sentimentPercent(sentiment)"
            :color="sentiment?.overall === 'positive' ? '#10b981' : sentiment?.overall === 'negative' ? '#ef4444' : '#6b7280'"
            :rail-color="'rgba(255,255,255,0.1)'"
            :height="6"
            style="margin-top: 8px"
          />
          <div class="stat-detail">
            评分: {{ sentiment?.score?.toFixed(3) || '0.000' }} · {{ sentiment?.total_articles || 0 }} 条新闻
          </div>
        </n-card>
      </n-grid-item>
      <n-grid-item>
        <n-card class="stat-card stat-alerts">
          <n-statistic label="活跃监控" :value="alerts.filter(a => a.is_active).length" />
          <div class="stat-detail">共 {{ alerts.length }} 条规则</div>
        </n-card>
      </n-grid-item>
      <n-grid-item>
        <n-card class="stat-card stat-winrate">
          <n-statistic label="新闻交易胜率" :value="(stats?.win_rate || 0) + '%'" />
          <div class="stat-detail">{{ stats?.total_trades || 0 }} 笔交易</div>
        </n-card>
      </n-grid-item>
      <n-grid-item>
        <n-card class="stat-card stat-pnl">
          <n-statistic
            label="新闻交易盈亏"
            :value="(stats?.total_pnl || 0).toFixed(2) + ' USDT'"
          />
          <div class="stat-detail">
            <span style="color:#10b981">{{ stats?.win_count || 0 }}胜</span> /
            <span style="color:#ef4444">{{ stats?.loss_count || 0 }}负</span>
          </div>
        </n-card>
      </n-grid-item>
    </n-grid>

    <!-- 主内容区: 新闻流 + 右侧面板 -->
    <div class="main-content">
      <!-- 新闻流 -->
      <div class="news-feed">
        <n-card title="实时新闻" class="feed-card">
          <!-- 筛选栏 -->
          <template #header-extra>
            <n-space :size="8">
              <n-select
                v-model:value="filterCategory"
                :options="[{ value: '', label: '全部分类' }, ...categoryOptions]"
                placeholder="分类"
                size="small"
                style="width: 140px"
                @update:value="loadNews"
              />
              <n-input
                v-model:value="filterKeyword"
                placeholder="搜索..."
                size="small"
                style="width: 120px"
                clearable
                @clear="loadNews"
                @keyup.enter="loadNews"
              />
              <n-button size="small" @click="loadNews" :loading="loading">刷新</n-button>
            </n-space>
          </template>

          <n-spin :show="loading && newsList.length === 0">
            <div v-if="newsList.length === 0 && !loading" style="padding: 40px 0">
              <n-empty description="暂无新闻数据，请配置 CryptoPanic API Key" />
            </div>
            <div v-else class="news-list">
              <div v-for="article in newsList" :key="article.id" class="news-item">
                <div class="news-header">
                  <n-tag
                    v-if="article.news_category"
                    :bordered="false"
                    size="small"
                    class="cat-tag"
                  >
                    {{ categoryMap[article.news_category] || article.news_category }}
                  </n-tag>
                  <n-tag
                    v-if="article.sentiment"
                    :bordered="false"
                    size="small"
                    :color="{ color: sentimentColor[article.sentiment] + '20', textColor: sentimentColor[article.sentiment] }"
                  >
                    {{ article.sentiment === 'positive' ? '📈 看多' : article.sentiment === 'negative' ? '📉 看空' : '➖ 中性' }}
                  </n-tag>
                  <n-tag
                    v-if="article.importance === 'high'"
                    :bordered="false"
                    size="small"
                    type="warning"
                  >
                    🔥 重要
                  </n-tag>
                  <span class="news-time">{{ formatTime(article.published_at) }}</span>
                </div>
                <div class="news-title">
                  <a :href="article.url" target="_blank" rel="noopener">
                    {{ article.title_zh || article.title }}
                  </a>
                </div>
                <div v-if="article.title_zh" class="news-title-en">
                  {{ article.title }}
                </div>
                <div class="news-meta">
                  <span v-if="article.currencies && article.currencies.length > 0" class="currencies">
                    <n-tag v-for="c in article.currencies" :key="c" size="tiny" :bordered="false">{{ c }}</n-tag>
                  </span>
                  <span class="source">{{ article.source }}</span>
                </div>
              </div>
            </div>
          </n-spin>
        </n-card>
      </div>

      <!-- 右侧: 监控规则 + AI思考 -->
      <div class="side-panel">
        <!-- 监控规则 -->
        <n-card title="📋 监控规则" class="alerts-card">
          <template #header-extra>
            <n-button size="small" type="primary" @click="showCreateAlert = true">
              + 新建
            </n-button>
          </template>

          <div v-if="alerts.length === 0" style="padding: 16px 0">
            <n-empty description="暂无监控规则" size="small" />
          </div>
          <div v-else class="alert-list">
            <div v-for="alert in alerts" :key="alert.id" class="alert-item" :class="{ inactive: !alert.is_active }">
              <div class="alert-header">
                <span class="alert-name">{{ alert.name }}</span>
                <n-space :size="4">
                  <n-tooltip>
                    <template #trigger>
                      <n-switch
                        :value="alert.is_active"
                        size="small"
                        @update:value="toggleAlert(alert)"
                      />
                    </template>
                    {{ alert.is_active ? '点击暂停' : '点击启用' }}
                  </n-tooltip>
                </n-space>
              </div>
              <div class="alert-keywords">
                <n-tag v-for="kw in (alert.keywords || [])" :key="kw" size="tiny" :bordered="false">{{ kw }}</n-tag>
              </div>
              <div class="alert-stats">
                <span>触发 {{ alert.triggered_count }}次</span>
                <span v-if="alert.action === 'trade'" :style="{ color: alert.total_pnl >= 0 ? '#10b981' : '#ef4444' }">
                  {{ alert.win_rate }}% 胜率 · {{ alert.total_pnl >= 0 ? '+' : '' }}{{ alert.total_pnl.toFixed(2) }} USDT
                </span>
              </div>
              <div class="alert-actions">
                <n-button
                  size="tiny"
                  :type="alert.is_reliable ? 'default' : 'warning'"
                  :ghost="alert.is_reliable"
                  @click="toggleReliable(alert)"
                >
                  {{ alert.is_reliable ? '可靠' : '⚠️ 不可靠' }}
                </n-button>
                <n-popconfirm @positive-click="onDeleteAlert(alert.id)">
                  <template #trigger>
                    <n-button size="tiny" type="error" ghost>删除</n-button>
                  </template>
                  确定删除此监控规则？
                </n-popconfirm>
              </div>
            </div>
          </div>
        </n-card>

        <!-- AI 思考记录 -->
        <n-card title="🧠 AI 思考记录" class="thinking-card" style="margin-top: 16px">
          <div v-if="thinkings.length === 0" style="padding: 16px 0">
            <n-empty description="暂无思考记录" size="small" />
          </div>
          <n-collapse v-else>
            <n-collapse-item
              v-for="t in thinkings"
              :key="t.id"
              :title="t.step_get_news || `思考 #${t.id}`"
              :name="t.id"
            >
              <div class="thinking-steps">
                <div v-if="t.step_get_news" class="step"><strong>① 获取:</strong> {{ t.step_get_news }}</div>
                <div v-if="t.step_analyze" class="step"><strong>② 分析:</strong> {{ t.step_analyze }}</div>
                <div v-if="t.step_evaluate" class="step"><strong>③ 评估:</strong> {{ t.step_evaluate }}</div>
                <div v-if="t.step_decide" class="step"><strong>④ 决策:</strong> {{ t.step_decide }}</div>
                <n-divider v-if="t.ai_reflection" style="margin: 8px 0" />
                <div v-if="t.ai_reflection" class="step"><strong>💭 反思:</strong> {{ t.ai_reflection }}</div>
                <div class="thinking-result">
                  <n-tag :type="t.decision === 'trade' ? 'success' : t.decision === 'skip' ? 'default' : 'warning'" size="small">
                    {{ t.decision === 'trade' ? '📊 交易' : t.decision === 'skip' ? '⏭️ 跳过' : '👀 观察' }}
                  </n-tag>
                  <span v-if="t.trade_result" :style="{ color: t.trade_result === 'win' ? '#10b981' : '#ef4444' }">
                    {{ t.trade_result === 'win' ? '✅ 盈利' : '❌ 亏损' }}
                    {{ t.trade_pnl ? (t.trade_pnl >= 0 ? '+' : '') + t.trade_pnl.toFixed(2) + ' USDT' : '' }}
                  </span>
                </div>
              </div>
            </n-collapse-item>
          </n-collapse>
        </n-card>
      </div>
    </div>

    <!-- 创建监控规则弹窗 -->
    <n-modal v-model:show="showCreateAlert" preset="card" title="新建监控规则" style="width: 560px">
      <n-form label-placement="left" label-width="100" :model="alertForm">
        <n-form-item label="规则名称">
          <n-input v-model:value="alertForm.name" placeholder="如: 美联储降息做多" />
        </n-form-item>
        <n-form-item label="关键词">
          <n-input v-model:value="alertForm.keywords" placeholder="多个关键词用逗号隔开, 如: 降息,rate cut,Fed" />
        </n-form-item>
        <n-form-item label="关注币种">
          <n-input v-model:value="alertForm.currencies" placeholder="如: BTC,ETH (留空=全部)" />
        </n-form-item>
        <n-form-item label="新闻分类">
          <n-select v-model:value="alertForm.news_categories" :options="categoryOptions" multiple placeholder="选择分类 (留空=全部)" />
        </n-form-item>
        <n-form-item label="情感过滤">
          <n-select
            v-model:value="alertForm.sentiment_filter"
            :options="[
              { value: 'any', label: '全部' },
              { value: 'positive', label: '仅看多' },
              { value: 'negative', label: '仅看空' },
            ]"
          />
        </n-form-item>
        <n-form-item label="动作">
          <n-select
            v-model:value="alertForm.action"
            :options="[
              { value: 'notify', label: '📢 仅通知' },
              { value: 'trade', label: '📊 自动交易' },
            ]"
          />
        </n-form-item>

        <template v-if="alertForm.action === 'trade'">
          <n-divider>交易参数</n-divider>
          <n-form-item label="交易方向">
            <n-select
              v-model:value="alertForm.trade_side"
              :options="[{ value: 'buy', label: '做多' }, { value: 'sell', label: '做空' }]"
            />
          </n-form-item>
          <n-form-item label="交易对">
            <n-input v-model:value="alertForm.trade_symbol" placeholder="BTCUSDT" />
          </n-form-item>
          <n-form-item label="仓位%">
            <n-input-number v-model:value="alertForm.trade_position_pct" :min="1" :max="15" :step="1" />
          </n-form-item>
          <n-form-item label="杠杆">
            <n-input-number v-model:value="alertForm.trade_leverage" :min="1" :max="20" :step="1" />
          </n-form-item>
          <n-form-item label="止损%">
            <n-input-number v-model:value="alertForm.trade_stop_loss_pct" :min="0.5" :max="20" :step="0.5" />
          </n-form-item>
          <n-form-item label="止盈%">
            <n-input-number v-model:value="alertForm.trade_take_profit_pct" :min="0.5" :max="50" :step="0.5" />
          </n-form-item>
        </template>
      </n-form>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showCreateAlert = false">取消</n-button>
          <n-button type="primary" @click="onCreateAlert" :loading="alertSaving">创建</n-button>
        </n-space>
      </template>
    </n-modal>
    </div>
  </MainLayout>
</template>

<style scoped>
.news-center {
  padding: 24px;
  max-width: 1400px;
  margin: 0 auto;
}
.page-header {
  margin-bottom: 20px;
}
.page-header h1 {
  font-size: 28px;
  font-weight: 700;
  margin: 0;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}
.subtitle {
  color: #888;
  font-size: 14px;
  margin-top: 4px;
}

/* 统计卡片 */
.stats-grid {
  margin-bottom: 20px;
}
.stat-card {
  border-radius: 12px;
  border: 1px solid rgba(255,255,255,0.06);
  background: rgba(255,255,255,0.02);
}
.stat-detail {
  font-size: 12px;
  color: #888;
  margin-top: 6px;
}

/* 主内容 */
.main-content {
  display: grid;
  grid-template-columns: 1fr 380px;
  gap: 16px;
}

/* 新闻列表 */
.feed-card {
  border-radius: 12px;
}
.news-list {
  max-height: 600px;
  overflow-y: auto;
}
.news-item {
  padding: 12px 0;
  border-bottom: 1px solid rgba(255,255,255,0.06);
}
.news-item:last-child {
  border-bottom: none;
}
.news-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
  flex-wrap: wrap;
}
.news-time {
  font-size: 12px;
  color: #666;
  margin-left: auto;
}
.news-title {
  font-size: 15px;
  line-height: 1.5;
}
.news-title a {
  color: #e0e0e0;
  text-decoration: none;
  transition: color 0.2s;
}
.news-title a:hover {
  color: #667eea;
}
.news-title-en {
  font-size: 12px;
  color: #666;
  margin-top: 2px;
}
.news-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 6px;
}
.currencies {
  display: flex;
  gap: 4px;
}
.source {
  font-size: 11px;
  color: #555;
}
.cat-tag {
  background: rgba(102, 126, 234, 0.15);
  color: #8b9cf7;
}

/* 监控规则 */
.alerts-card, .thinking-card {
  border-radius: 12px;
}
.alert-list {
  max-height: 300px;
  overflow-y: auto;
}
.alert-item {
  padding: 10px;
  border-radius: 8px;
  background: rgba(255,255,255,0.02);
  margin-bottom: 8px;
  border: 1px solid rgba(255,255,255,0.06);
  transition: opacity 0.2s;
}
.alert-item.inactive {
  opacity: 0.5;
}
.alert-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}
.alert-name {
  font-weight: 600;
  font-size: 14px;
}
.alert-keywords {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
  margin-bottom: 6px;
}
.alert-stats {
  font-size: 12px;
  color: #888;
  display: flex;
  gap: 12px;
  margin-bottom: 6px;
}
.alert-actions {
  display: flex;
  gap: 6px;
}

/* AI 思考记录 */
.thinking-steps {
  font-size: 13px;
  line-height: 1.8;
}
.step {
  margin-bottom: 4px;
}
.thinking-result {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
}

@media (max-width: 900px) {
  .main-content {
    grid-template-columns: 1fr;
  }
  .stats-grid :deep(.n-grid) {
    grid-template-columns: repeat(2, 1fr) !important;
  }
}
</style>
