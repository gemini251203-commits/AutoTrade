# AutoTrade 前端样式优化指南

## 目标

对 AutoTrade 交易系统的前端进行纯样式优化，确保:
1. 手机端能正常打开所有页面，布局自适应，无溢出
2. 所有内容完整展示，无遮挡、无重叠、无截断
3. 视觉风格统一，间距合理，排版一致
4. 不引入新 bug，不改变任何功能逻辑

---

## 技术栈

- 框架: Vue 3 + TypeScript
- UI 库: Naive UI
- 样式: Scoped CSS (每个 .vue 文件内 `<style scoped>`)
- 全局样式: `src/style.css`
- 布局: `src/layouts/MainLayout.vue` (侧边栏 + 顶栏 + 底部导航)
- 路由: `src/router/index.ts`

---

## 可以修改的内容

### 1. 样式代码 (<style> 部分)
- 每个 .vue 文件的 `<style scoped>` 块
- `src/style.css` 全局样式
- CSS 属性: 颜色、字号、间距、布局、响应式断点、动画
- 添加 `@media` 查询实现移动端适配
- 修改 Tailwind/自定义 class 的样式值

### 2. 模板结构 (<template> 部分)
- 仅限于为响应式布局调整 HTML 结构
- 例如: 将 grid 改为 flex，调整嵌套层级以修复布局问题
- 添加包装容器 div 以实现滚动或对齐
- 添加 CSS class 名
- 条件性隐藏/显示元素 (v-if/v-show 基于屏幕尺寸)

### 3. Naive UI 组件属性
- `:cols`、`:x-gap`、`:y-gap` 等布局属性
- `size`、`placement` 等展示属性
- `theme-overrides` 样式覆盖对象

---

## 禁止修改的内容

### 1. 后端代码
- `backend/` 目录下的所有文件不得修改
- API 端点、数据模型、业务逻辑一律不动

### 2. 前端逻辑 (<script> 部分)
- API 调用函数和参数
- 数据处理、计算属性的计算逻辑
- 路由配置和导航守卫
- Store 的 state/action/getter 逻辑
- 事件处理函数的业务逻辑
- TypeScript 类型定义

### 3. 功能行为
- 按钮的点击行为
- 表单提交逻辑
- WebSocket 连接
- 认证流程
- 数据刷新机制

### 4. 文件结构
- 不新增、不删除、不重命名文件
- 不修改 `package.json` 依赖
- 不修改 `vite.config.ts` 构建配置
- 不修改 `docker-compose.yml` 或 `nginx.conf`

---

## 页面清单与优化重点

### 布局组件
| 文件 | 说明 | 优化重点 |
|------|------|---------|
| `layouts/MainLayout.vue` | 主布局 (侧栏+顶栏+底部导航) | 移动端底部导航间距、顶栏信息在小屏的折叠 |
| `App.vue` | 根组件 | viewport meta 确认、全局字体 |
| `style.css` | 全局样式 | 基础重置、滚动条、通用工具类 |

### 页面视图
| 文件 | 说明 | 优化重点 |
|------|------|---------|
| `views/Dashboard.vue` | 交易面板 (图表+仓位+下单) | 移动端图表高度、下单面板折叠、仓位列表横向滚动 |
| `views/Wallet.vue` | 投资组合 (日历PnL+摘要统计) | 日历表格在小屏的横向溢出、统计卡片堆叠 |
| `views/SignalAssistant.vue` | AI信号助手 | 移动端两栏改单栏、输入区域宽度 |
| `views/Settings.vue` | 系统设置 | 表单在移动端的宽度和间距 |
| `views/ChatAgent.vue` | AI Agent 聊天 | 聊天气泡宽度、输入框底部固定 |
| `views/StrategyManager.vue` | 量化策略 | 表格横向滚动、弹窗在小屏的尺寸 |
| `views/TradeJournal.vue` | 交易日志 | 表格响应式、筛选器折叠 |
| `views/NewsCenter.vue` | 新闻中心 | 新闻卡片网格自适应 |
| `views/AutopilotDashboard.vue` | 自动交易 | 状态卡片和日志列表的移动端布局 |
| `views/Login.vue` | 登录页 | 居中对齐、小屏表单宽度 |
| `views/Admin.vue` | 管理后台 | 管理面板响应式 |

### 业务组件
| 文件 | 说明 | 优化重点 |
|------|------|---------|
| `components/TradePanel.vue` | 下单面板 | 输入框排列、按钮间距 |
| `components/TradingChart.vue` | K线图表 | 高度自适应 |
| `components/PositionList.vue` | 持仓列表 | 移动端表格横向滚动、数字截断 |
| `components/OrderList.vue` | 订单列表 | 同上 |
| `components/GridTrading.vue` | 网格交易 | 参数面板移动端布局 |
| `components/AccountMenu.vue` | 账户菜单 | 下拉菜单定位 |
| `components/SkeletonCard.vue` | 骨架屏 | 尺寸与实际卡片一致 |

---

## 移动端适配要求

1. 断点: `768px` (md) 作为手机/桌面分界
2. 所有页面在 375px 宽度下无水平滚动条
3. 表格类内容使用 `overflow-x: auto` 包裹
4. 数字和金额使用 `font-variant-numeric: tabular-nums`
5. 触摸目标最小 44px (按钮、链接)
6. 底部导航预留 `safe-area-inset-bottom`
7. 输入框不被键盘遮挡

---

## 验证清单

完成优化后逐条检查:

- [ ] 所有 11 个页面在桌面端 (1920px) 正常显示
- [ ] 所有 11 个页面在手机端 (375px) 正常显示
- [ ] 无 console 报错
- [ ] TypeScript 编译零错误 (`npx vue-tsc --noEmit`)
- [ ] 侧栏导航全部可点击跳转
- [ ] 底部导航全部可点击跳转
- [ ] 无内容溢出或截断
- [ ] 无元素重叠
- [ ] 所有弹窗在移动端可正常打开和关闭
- [ ] 图表在移动端可正常渲染
