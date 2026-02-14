#!/bin/bash
# ============================================
# AutoTrade 一键部署脚本
# ============================================
# 使用方法:
#   chmod +x deploy.sh
#   ./deploy.sh
# ============================================

set -e  # 遇错即停

echo "========================================"
echo "       AutoTrade 一键部署脚本          "
echo "========================================"

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 检查 Docker
check_docker() {
    echo -e "${YELLOW}[1/5] 检查 Docker 环境...${NC}"
    if ! command -v docker &> /dev/null; then
        echo -e "${RED}❌ Docker 未安装!${NC}"
        echo "请先安装 Docker: https://docs.docker.com/engine/install/ubuntu/"
        exit 1
    fi
    if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
        echo -e "${RED}❌ Docker Compose 未安装!${NC}"
        exit 1
    fi
    echo -e "${GREEN}✅ Docker 环境正常${NC}"
}

# 创建环境配置
create_env() {
    echo -e "${YELLOW}[2/5] 检查环境配置...${NC}"
    if [ ! -f .env ]; then
        echo "创建 .env 文件..."
        cat > .env << EOF
# ==========================================
# AutoTrade 生产环境配置
# ==========================================

# 数据库密码 (请修改!)
DB_PASSWORD=autotrade_secret_2026

# JWT 密钥 (请修改为随机字符串!)
JWT_SECRET_KEY=$(openssl rand -hex 32)

# AI 配置 (可选)
OLLAMA_BASE_URL=http://host.docker.internal:11434
OLLAMA_MODEL=deepseek-r1:14b

# 交易模式
TRADING_MODE=simulation
SIMULATION_INITIAL_BALANCE=10000
EOF
        echo -e "${GREEN}✅ 已创建 .env 文件，请检查配置${NC}"
    else
        echo -e "${GREEN}✅ .env 文件已存在${NC}"
    fi
}

# 创建目录
create_dirs() {
    echo -e "${YELLOW}[3/5] 创建必要目录...${NC}"
    mkdir -p backend/logs
    mkdir -p nginx/ssl
    echo -e "${GREEN}✅ 目录创建完成${NC}"
}

# 构建镜像
build_images() {
    echo -e "${YELLOW}[4/5] 构建 Docker 镜像...${NC}"
    docker compose build --no-cache
    echo -e "${GREEN}✅ 镜像构建完成${NC}"
}

# 启动服务
start_services() {
    echo -e "${YELLOW}[5/5] 启动服务...${NC}"
    docker compose up -d
    
    # 等待服务启动
    echo "等待服务启动..."
    sleep 10
    
    # 检查服务状态
    echo ""
    echo "========================================"
    echo "        服务状态                        "
    echo "========================================"
    docker compose ps
    
    # 健康检查
    echo ""
    echo "========================================"
    echo "        健康检查                        "
    echo "========================================"
    
    if curl -s http://localhost:8000/health > /dev/null 2>&1 || curl -s http://localhost/api/health > /dev/null 2>&1; then
        echo -e "${GREEN}✅ 后端服务正常${NC}"
    else
        echo -e "${YELLOW}⚠️  后端服务启动中...${NC}"
    fi
    
    if curl -s http://localhost > /dev/null 2>&1; then
        echo -e "${GREEN}✅ 前端服务正常${NC}"
    else
        echo -e "${YELLOW}⚠️  前端服务启动中...${NC}"
    fi
}

# 显示完成信息
show_success() {
    echo ""
    echo "========================================"
    echo -e "${GREEN}       🎉 部署完成!                    ${NC}"
    echo "========================================"
    echo ""
    echo "访问地址:"
    echo "  - 前端: http://$(hostname -I | awk '{print $1}')"
    echo "  - API:  http://$(hostname -I | awk '{print $1}')/api"
    echo ""
    echo "管理命令:"
    echo "  - 查看日志: docker compose logs -f"
    echo "  - 停止服务: docker compose down"
    echo "  - 重启服务: docker compose restart"
    echo ""
    echo "默认账户:"
    echo "  - 用户名: admin"
    echo "  - 密码: admin"
    echo ""
    echo "========================================"
}

# 主流程
main() {
    check_docker
    create_env
    create_dirs
    build_images
    start_services
    show_success
}

main "$@"
