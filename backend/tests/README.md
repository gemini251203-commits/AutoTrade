# Backend Tests

## 目录结构

```
tests/
├── __init__.py
├── README.md                    # 本文件
├── test_trading_logic.py        # 交易核心逻辑测试 (费率/滑点/P&L/保证金/止盈止损/强平/资金流转)
├── test_circuit_breaker.py      # API 断路器状态机测试 (CLOSED→OPEN→HALF_OPEN→恢复)
├── test_encryption.py           # API Key 加密/解密/脱敏/多格式兼容测试
├── test_risk_model.py           # 风控配置加载 (默认值/类型安全/热加载/边界检查)
└── test_grid_strategy.py        # 网格策略算法测试 (等差/等比网格/数量计算/利润计算)
```

## 运行方式

### 纯逻辑单元测试 (无需后端服务)

```bash
cd backend

# 运行全部单元测试
python -m pytest tests/ -v

# 运行单个测试文件
python -m pytest tests/test_trading_logic.py -v
python -m pytest tests/test_circuit_breaker.py -v
python -m pytest tests/test_encryption.py -v
python -m pytest tests/test_risk_model.py -v
python -m pytest tests/test_grid_strategy.py -v
```

### 测试分类

| 文件 | 类别 | 依赖 | 说明 |
|------|------|------|------|
| `test_trading_logic.py` | 单元测试 | 无外部依赖 | 交易引擎核心公式验证 |
| `test_circuit_breaker.py` | 单元测试 | 无外部依赖 | 断路器状态机转换逻辑 |
| `test_encryption.py` | 单元测试 | 需 `cryptography` 包 | API Key 安全存储验证 |
| `test_risk_model.py` | 单元测试 | 需 `pyyaml` 包 | 风控参数加载与验证 |
| `test_grid_strategy.py` | 单元测试 | 无外部依赖 | 网格价格数学计算 |
