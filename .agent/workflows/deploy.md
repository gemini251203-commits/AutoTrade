---
description: Deploy AutoTrade to production server (45.77.26.211)
---

# 部署 AutoTrade 到服务器

## 前置条件
- 服务器已安装 Docker 和 Docker Compose
- 已配置 SSH 免密登录 (`ssh root@45.77.26.211`)
- GitHub 仓库: `https://github.com/gemini251203-commits/AutoTrade.git`

## 首次部署

### 1. SSH 登录服务器
```bash
ssh root@45.77.26.211
```

### 2. 克隆仓库
```bash
cd /root
git clone https://github.com/gemini251203-commits/AutoTrade.git
cd AutoTrade
```

### 3. 配置环境变量
```bash
# 创建 .env 文件 (仅首次)
cat > .env << 'EOF'
JWT_SECRET_KEY=your-strong-secret-key-change-this
EOF
```

### 4. 启动所有服务
```bash
docker compose up -d --build
```

### 5. 验证
```bash
docker compose ps
curl http://localhost/api/health
```

---

## 日常更新部署 (一条命令)

在服务器上执行:
```bash
cd /root/AutoTrade && git pull && docker compose up -d --build
```

或者从本地 Windows 一键远程部署:
```powershell
ssh root@45.77.26.211 "cd /root/AutoTrade && git pull && docker compose up -d --build"
```

---

## 本地推送 + 远程部署 (完整流程)

// turbo-all

### 1. 本地推送到 GitHub
```powershell
cd D:\AutoTrade
git push origin main
```

### 2. 远程部署
```powershell
ssh root@45.77.26.211 "cd /root/AutoTrade && git pull && docker compose up -d --build"
```

### 3. 检查服务状态
```powershell
ssh root@45.77.26.211 "cd /root/AutoTrade && docker compose ps"
```

---

## 回滚
```bash
# 在服务器上
cd /root/AutoTrade
git log --oneline -5          # 查看最近 5 个 commit
git checkout <commit-hash>    # 切换到目标版本
docker compose up -d --build  # 重新构建
```

## 查看日志
```bash
docker compose logs -f backend    # 后端日志
docker compose logs -f frontend   # 前端日志
docker compose logs -f db         # 数据库日志
```
