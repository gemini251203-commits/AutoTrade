# 前端 UI 优化指南 — 给 AI 的提示词

## 🎯 目标
优化 AutoTrade 前端的**视觉效果和用户体验**，使界面更现代、更美观。

## 🚨 绝对不能改的东西（红线）

### 1. API 接口调用 — 一个字都不能改
所有 API 调用定义在 `src/api/` 目录下，包括：
- `src/api/chat.ts` — AI 对话 & 自动驾驶接口
- `src/api/` 下的所有其他文件

**不能改的内容：**
- 接口路径（如 `/api/orders/`、`/api/positions/` 等）
- 请求参数名和类型
- 响应数据的字段名
- TypeScript 接口定义（interface / type）
- 任何 import 来自 `src/api/` 的内容

### 2. 路由配置 — 不能改
- `src/router/index.ts` — 路由路径和组件映射不能动

### 3. 业务逻辑 — 不能改
每个 `.vue` 文件中 `<script setup>` 部分的以下内容**绝对不能修改**：
- `ref()` / `reactive()` / `computed()` 的变量名和逻辑
- 所有函数名和函数内部逻辑
- `onMounted()` / `watch()` / `onUnmounted()` 等生命周期
- API 调用的代码（axios / fetch）
- 事件处理函数（`handleXxx`、`onXxx`）
- 条件判断逻辑（`v-if` / `v-show` 的条件表达式）
- `v-for` 的数据绑定（`:key`、迭代变量）
- `v-model` 绑定的变量
- `emit` 事件名
- `props` 定义

### 4. 组件引用 — 不能改
- 不能删除任何已有的组件 import
- 不能删除任何已在使用的 Naive UI 组件

### 5. 布局结构中已绑定数据的元素 — 不能改
- 已有的 `{{ variable }}` 插值绑定不能删
- 已有的 `:prop="value"` 动态绑定不能删
- 已有的 `@event="handler"` 事件绑定不能删

## ✅ 可以改的东西

### 1. CSS / 样式（主要改这里）
- `<style>` 部分可以自由修改
- 颜色、字体、间距、圆角、阴影、渐变
- 动画和过渡效果（transition / animation）
- 响应式布局调整（media query）
- 暗色模式优化

### 2. HTML 结构（小心地改）
- 可以**包裹**现有元素（加外层 div）
- 可以**添加**纯装饰性元素（图标、分隔线、背景层）
- 可以调整元素的 CSS class 名称
- 可以给 Naive UI 组件添加样式属性（如 `:style`、`:theme-overrides`）

### 3. 新增纯展示性组件
- 可以新建纯 UI 组件（如 `SkeletonCard.vue`、`GlowEffect.vue`）
- 但不能包含任何业务逻辑或 API 调用

## 📋 技术栈信息
- **框架**: Vue 3 (Composition API, `<script setup>`)
- **UI 库**: Naive UI
- **图标**: @vicons/ionicons5
- **构建**: Vite
- **语言**: TypeScript

## 🧪 改完后的验证标准
1. `npm run build` 零错误零警告
2. 所有页面能正常打开，不白屏
3. 所有按钮/表单/弹窗功能正常
4. 所有 API 调用正常（网络请求没变化）
5. 所有数据展示正确（数字、状态、列表）

## 📄 需要优化的页面列表
| 页面 | 文件路径 | 功能 |
|------|----------|------|
| 登录 | `src/views/Login.vue` | 登录和注册 |
| 仪表盘 | `src/views/Dashboard.vue` | 主交易面板（K线图、下单、仓位、订单） |
| 钱包 | `src/views/Wallet.vue` | 余额、充值、交易流水 |
| 信号助手 | `src/views/SignalAssistant.vue` | 喊单文本解析 |
| AI 对话 | `src/views/ChatAgent.vue` | AI 聊天界面 |
| 自动驾驶 | `src/views/AutopilotDashboard.vue` | 自动交易面板 |
| 策略管理 | `src/views/StrategyManager.vue` | YAML 策略管理 |
| 交易日志 | `src/views/TradeJournal.vue` | 历史交易记录 |
| 设置 | `src/views/Settings.vue` | AI 配置 |
| 管理员 | `src/views/Admin.vue` | 用户管理 |
| 侧边栏 | `src/layouts/MainLayout.vue` | 主布局和导航 |

## 🎨 设计方向建议
- 现代暗色主题（深色背景 + 亮色强调）
- 毛玻璃效果（glassmorphism）
- 微交互动画（hover、点击反馈）
- 渐变色按钮和卡片
- 数据可视化增强（图表、进度条）
- 交易相关用红绿配色（涨绿跌红 或 涨红跌绿）
