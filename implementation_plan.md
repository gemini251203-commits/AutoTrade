# AI Agent 提示词工程标准化 + 管理系统

## 背景

当前 AutoTrade 系统中存在 **三层提示词架构**：

1. **全局系统概览** (`SYSTEM_OVERVIEW` in [brain.py](file:///d:/AutoTrade/backend/app/services/hub/brain.py#L31-L77)) — 所有 Hub Agent 共享的基础人格和工作方式
2. **Agent 专属指令** (`system_prompt` in [hub_agent.py](file:///d:/AutoTrade/backend/app/models/hub_agent.py#L97-L101)) — 用户在前端编辑框中手写的自定义指令
3. **值班周期指令** (`_build_cycle_prompt` in [daemon.py](file:///d:/AutoTrade/backend/app/services/hub/daemon.py#L518-L571)) — 每次轮询时系统自动注入的任务指令

**核心问题**：
- 用户（你）在前端 System Prompt 编辑框中写的内容，与系统自动注入的指令**混杂且重叠**
- 没有方法追踪"哪个提示词赚了钱"
- 没有版本管理和市况适配机制
- 不清楚AI到底能识别哪些格式的指令

---

## 研究发现：AI 能准确识别的提示词结构

> [!IMPORTANT]
> 以下是基于对 DeepSeek/OpenAI 模型行为的研究，总结出 AI **确实能识别和遵循** 的提示词语法规范。

### ✅ AI 能精确理解的指令类型

| 类型 | 格式 | AI的理解能力 | 示例 |
|------|------|-------------|------|
| **角色设定** | `你是...` / `你的角色是...` | ⭐⭐⭐⭐⭐ | "你是保守型交易员，只在确认信号后入场" |
| **硬性规则** | `禁止...` / `必须...` / `绝对不...` | ⭐⭐⭐⭐⭐ | "禁止同时持有超过3个仓位" |
| **数值限制** | 具体数字 + 条件 | ⭐⭐⭐⭐⭐ | "单笔仓位不超过账户余额的20%" |
| **条件逻辑** | `如果...则...` / `当...时...` | ⭐⭐⭐⭐ | "如果RSI>70，则禁止做多" |
| **优先级排序** | `最重要` / `其次` / `最后` | ⭐⭐⭐⭐ | "资金安全第一，盈利第二" |
| **结构化标签** | `【】` / `##` / `- ` | ⭐⭐⭐⭐ | "【风控规则】..." |
| **反面示例** | `❌ 错误: ...` / `✅ 正确: ...` | ⭐⭐⭐⭐ | "❌ 追涨杀跌 ✅ 等回调入场" |
| **模糊策略** | "注意风险" / "谨慎操作" | ⭐⭐ | 太模糊，AI 会自行解读 |
| **矛盾指令** | 两条互相矛盾的规则 | ⭐ | AI 会随机选择，行为不稳定 |

### 推荐的提示词结构模板

```
【身份定义】
你是...，你的交易风格是...

【交易策略 - 核心规则】
1. 趋势判断：...
2. 入场条件：...
3. 仓位管理：...

【风控规则 - 最高优先级】
- 禁止...
- 必须...
- 当...时，必须...

【特殊市况处理】
- 剧烈波动时：...
- 横盘震荡时：...
- 单边趋势时：...

【禁止行为清单】
❌ ...
❌ ...
```

---

## 提出的建议

> [!TIP]
> 基于系统分析，我建议构建一个 **提示词模板管理系统**，而不是每次都手工编写提示词。

### 建议 1: 分离"策略提示词"和"系统指令"

**现状问题**：用户在 System Prompt 编辑框中混写了策略规则和系统行为指令（如效率规则、回复格式），但系统已经在 `SYSTEM_OVERVIEW` 中注入了这些内容，导致 **重复和冲突**。

**方案**：将 Agent 的 `system_prompt` 字段拆分为两个明确的输入区域：
- **策略模板 (Strategy Template)** — 交易策略、风控规则、市况判断（用户写的核心内容）
- **行为指令 (Behavior Directives)** — 回复风格、效率要求（系统默认，高级用户可覆盖）

### 建议 2: 提示词版本管理 + 收益追踪

**核心需求**：知道"哪个提示词赚了钱"。

**方案**：
1. 新增 `prompt_templates` 数据库表，存储提示词版本
2. Agent 每次执行时记录当前使用的 `prompt_version_id`
3. 将 `prompt_version_id` 关联到 Position/Order，实现 **提示词 → 交易 → 盈亏** 的完整追踪链
4. 前端提供仪表盘，展示每个提示词版本的**胜率、总盈亏、夏普比率**

### 建议 3: 市况标签系统

为每个提示词模板标记适用的市况：
- **趋势上涨** / **趋势下跌** / **横盘震荡** / **剧烈波动**
- **小资金 (<1000U)** / **中资金 (1000-10000U)** / **大资金 (>10000U)**
- 系统根据趋势引擎的实时判断，**自动推荐**最适合的提示词模板

### 建议 4: 预置策略模板库

提供经过测试的提示词模板，用户可以一键应用：
- 🛡️ **保守防守型** — 只做高确定性交易，严格止损
- ⚔️ **趋势追踪型** — 顺势操作，金字塔加仓
- 🔄 **震荡网格型** — 区间交易，自动网格
- 🎯 **事件驱动型** — 基于新闻和情绪交易

---

## 具体实施方案

### Phase 1: 提示词模板管理后端 (数据层)

#### [NEW] [prompt_template.py](file:///d:/AutoTrade/backend/app/models/prompt_template.py)

新建提示词模板数据模型：

```python
class PromptTemplate(Base):
    __tablename__ = "prompt_templates"
    
    id              # 主键
    user_id         # 所属用户
    name            # 模板名称 (如 "保守交易v3")
    version         # 版本号 (自增)
    
    # 内容分区
    strategy_prompt # 交易策略描述
    risk_rules      # 风控规则
    market_tags     # 适用市况标签 JSON: ["trending_up", "small_fund"]
    
    # 元数据
    is_active       # 是否为 Agent 当前使用的版本
    parent_id       # 从哪个版本fork/演化而来 (版本树)
    
    # 收益追踪
    total_trades    # 使用此模板产生的交易数
    total_pnl       # 使用此模板的总盈亏
    win_rate        # 胜率
    
    created_at
```

#### [NEW] [prompt_activation_log.py](file:///d:/AutoTrade/backend/app/models/prompt_activation_log.py)

提示词激活日志 — 记录每次 Agent 执行时使用的提示词版本：

```python
class PromptActivationLog(Base):
    __tablename__ = "prompt_activation_logs"
    
    id
    user_id
    agent_id
    template_id     # 使用的提示词模板
    activated_at    # 激活时间
    deactivated_at  # 停用时间 (切换到其他模板时)
```

#### [MODIFY] [hub_agent.py](file:///d:/AutoTrade/backend/app/models/hub_agent.py)

- 新增 `active_template_id` 外键字段，关联到 `prompt_templates`
- 保留原有 `system_prompt` 字段作为兼容 (向后兼容)

#### [MODIFY] [Position 模型](file:///d:/AutoTrade/backend/app/models/position.py)

- 新增 `prompt_template_id` 字段，记录开仓时使用的提示词版本

---

### Phase 2: 提示词解析引擎 (后端服务)

#### [NEW] [prompt_engine.py](file:///d:/AutoTrade/backend/app/services/hub/prompt_engine.py)

提示词解析和组装引擎：

```python
class PromptEngine:
    """
    职责:
    1. 解析用户写的提示词，验证格式和完整性
    2. 把 PromptTemplate → 最终 system_prompt 组装
    3. 支持变量替换: {balance}, {market_regime}, {positions_count}
    4. 根据市况标签自动选择最佳模板
    """
    
    def build_prompt(template: PromptTemplate, context: dict) -> str:
        """组装完整提示词"""
    
    def validate_prompt(content: str) -> ValidationResult:
        """验证提示词格式，检查矛盾规则"""
    
    def suggest_template(market_regime: str, fund_size: float) -> PromptTemplate:
        """根据市况和资金量推荐最佳模板"""
```

#### [MODIFY] [brain.py](file:///d:/AutoTrade/backend/app/services/hub/brain.py)

- `_build_system_prompt()` 改为调用 `PromptEngine.build_prompt()`
- 每次执行时记录 `prompt_template_id` 到日志

#### [MODIFY] [daemon.py](file:///d:/AutoTrade/backend/app/services/hub/daemon.py)

- `_execute_cycle()` 中传递 `prompt_template_id` 到下单流程
- 将 `prompt_template_id` 写入 Position 的新字段

---

### Phase 3: 前端管理界面

#### [MODIFY] [AgentHub.vue](file:///d:/AutoTrade/frontend/src/views/AgentHub.vue)

改造 Agent 编辑弹窗：
- 原有的单个 "System Prompt" 文本框 → 模板选择器 + 分区编辑器
- 新增"策略"、"风控"、"市况"三个编辑分区
- 新增"从模板库导入"按钮

#### [NEW] [PromptManager.vue](file:///d:/AutoTrade/frontend/src/views/PromptManager.vue)

提示词管理中心页面：
- **模板列表** — 查看所有版本，对比不同版本的收益表现
- **版本历史** — 查看模板的演化历史（版本树）
- **收益仪表盘** — 各模板的胜率/盈亏/夏普比率排行
- **市况推荐** — 当前市况下系统推荐的最佳模板
- **模板编辑器** — 分区编辑 + 实时预览 + 格式校验

#### [NEW] [prompt.ts](file:///d:/AutoTrade/frontend/src/api/prompt.ts)

前端 API Client

---

### Phase 4: 收益追踪仪表盘

#### [NEW] [prompt_analytics.py](file:///d:/AutoTrade/backend/app/services/hub/prompt_analytics.py)

提示词收益分析服务：

```python
class PromptAnalytics:
    """
    分析各提示词版本的收益表现:
    - 总交易数、胜率、总盈亏
    - 按市况分组的表现 (趋势/震荡/波动)
    - 各资金阶段的表现
    - 推荐当前最优模板
    """
    
    async def get_template_performance(template_id) -> dict
    async def compare_templates(ids: list) -> dict
    async def get_best_template_for(market_regime, fund_size) -> PromptTemplate
```

#### [NEW] API 端点

```
GET    /api/prompts/templates          — 模板列表
POST   /api/prompts/templates          — 创建模板
PUT    /api/prompts/templates/{id}     — 更新模板
DELETE /api/prompts/templates/{id}     — 删除模板
POST   /api/prompts/templates/{id}/activate — 激活到指定 Agent
GET    /api/prompts/templates/{id}/performance — 收益分析
GET    /api/prompts/recommend          — 市况推荐
GET    /api/prompts/analytics/compare  — 跨模板对比
```

---

### Phase 5: 预置模板库

提供 4-6 个经过优化的提示词模板：

| 模板 | 适用市况 | 适用资金 | 核心特征 |
|------|---------|---------|---------|
| 🛡️ 保守防守 | 所有 | 所有 | 高确定性入场，严格止损，低杠杆 |
| ⚔️ 趋势追踪 | 趋势行情 | >500U | 顺势做多/空，金字塔加仓 |
| 🔄 震荡网格 | 横盘震荡 | >300U | 识别区间，开网格 |
| ⚡ 激进突破 | 剧烈波动 | >1000U | 追涨（突破），高杠杆短持 |
| 🧊 冷静观察 | 不确定 | 小资金 | 以观察和报告为主，极少交易 |
| 🎯 事件驱动 | 新闻驱动 | >500U | 新闻情绪+技术确认 |

---

## 开放问题

> [!WARNING]
> 以下问题需要你确认后才能开始实施。

1. **是否要保留原有的自由文本编辑？** 结构化模板会让写入更规范，但也会限制灵活性。建议：**保留高级模式**（原始文本），同时提供**引导式编辑器**作为默认模式。

2. **预置模板数量和内容**：你希望我根据截图中你当前的提示词内容，帮你提炼出第一批标准化模板吗？

3. **实施优先级**：
   - **最高**: Phase 1 (数据层) + Phase 5 (预置模板) — 让你能快速用上结构化提示词
   - **中**: Phase 2 (引擎) + Phase 3 (前端) — 管理界面
   - **低**: Phase 4 (收益追踪) — 需要数据积累后才有价值
   
   你是否同意这个优先级顺序？还是希望先做其他部分？

4. **市况自动推荐**：是否要实现"系统检测到市况变化时，自动切换提示词模板"？还是仅做推荐，手动切换？

5. **向后兼容**：现有 Agent 的 `system_prompt` 自由文本内容如何处理？是自动迁移为模板，还是保留原样？

---

## 验证计划

### 自动化测试
- 数据库迁移脚本正确执行 (Alembic)
- API 端点 CRUD 测试
- 提示词组装逻辑测试 (PromptEngine.build_prompt)
- 收益追踪关联正确性测试

### 手动验证
- 前端模板编辑器的用户体验
- Agent 使用模板执行交易，验证提示词正确注入
- 收益追踪数据是否正确关联到交易
- 部署到生产环境后的稳定性
