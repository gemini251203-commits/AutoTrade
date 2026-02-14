# Backend Tests

## 目录结构

```
tests/
├── integration/         # 全链路集成测试
│   ├── test_connection.py       # 网络连通性和 AI 服务测试
│   ├── test_dataflow.py         # API 端点和字段一致性测试
│   ├── test_dataflow_complete.py # 完整数据流验证 (Auth→Wallet→Position→Risk→Close)
│   └── test_simple.py           # 简化调试测试
├── grid/                # 网格交易测试
│   ├── test_grid.py             # 网格创建测试
│   ├── test_grid_start.py       # 网格启动测试
│   └── test_full_lifecycle.py   # 网格完整生命周期测试
└── wallet/              # 钱包测试
    └── test_wallet.py           # 多用户钱包隔离测试
```

## 运行方式

集成测试需要后端服务运行在 `localhost:8000`：

```bash
# 单个测试
python tests/integration/test_dataflow_complete.py

# 网格测试 (需要数据库连接)
python tests/grid/test_grid.py
```
