"""
AIBrain - AI 核心服务
======================
负责:
1. 解析用户喊单文本
2. 构建上下文数据
3. 调用 AI 生成结构化任务
"""

import json
import re
from decimal import Decimal
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field, asdict
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.models.user_ai_config import UserAIConfig, AIProvider
from app.models.wallet import Wallet
from app.models.position import Position, PositionStatus
from app.models.order import Order, OrderStatus
from app.models.grid_bot import GridBot, GridStatus
from app.core.encryption import decrypt_api_key
from .providers import BaseProvider, DeepSeekProvider, OllamaProvider, ChatMessage, ChatResponse


@dataclass
class MarketContext:
    """市场上下文"""
    symbol: str
    current_price: float
    price_change_24h: float = 0.0
    high_24h: float = 0.0
    low_24h: float = 0.0


@dataclass
class WalletContext:
    """钱包上下文"""
    balance: float
    available: float
    frozen: float
    equity: float


@dataclass
class PositionContext:
    """持仓上下文"""
    symbol: str
    side: str
    size: float
    entry_price: float
    unrealized_pnl: float
    leverage: int


@dataclass
class AIContext:
    """AI 完整上下文"""
    market: Optional[MarketContext] = None
    wallet: Optional[WalletContext] = None
    positions: List[PositionContext] = field(default_factory=list)
    pending_orders: int = 0
    running_grids: int = 0
    indicators: Optional[Dict[str, Any]] = None  # 技术指标
    timestamp: str = ""


@dataclass
class ParsedSignal:
    """解析后的交易信号"""
    # 基础信息
    symbol: str = ""
    side: str = ""  # long/short
    trade_style: str = ""  # left_side/right_side/market
    
    # 交易模式 (映射到 TradingMode)
    trading_mode: str = "market" 
    
    # 左侧交易: 入场价格
    entry_price: Optional[float] = None
    entry_low: Optional[float] = None
    entry_high: Optional[float] = None
    
    # 右侧交易: 突破条件
    trigger_price: Optional[float] = None
    max_deviation_pct: Optional[float] = 0.5
    confirm_interval: str = "15m"
    timeout_hours: int = 24
    
    # 止盈止损
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    take_profit_levels: List[float] = field(default_factory=list)
    
    # 资金管理
    leverage: int = 1
    margin: Optional[float] = None
    position_percent: Optional[float] = None
    
    # 分批建仓
    ladder_enabled: bool = False
    ladder_count: int = 1
    ladder_ratios: List[float] = field(default_factory=list)
    ladder_prices: List[float] = field(default_factory=list)
    
    # 网格参数
    is_grid: bool = False
    grid_lower: Optional[float] = None
    grid_upper: Optional[float] = None
    grid_count: Optional[int] = None
    grid_type: str = "arithmetic"
    grid_direction: str = "long"
    grid_investment: Optional[float] = None
    
    # AI 分析
    confidence: float = 0.0
    reasoning: str = ""
    warnings: List[str] = field(default_factory=list)


# 信号解析 Prompt
SIGNAL_PARSE_PROMPT = """你是一个专业的加密货币交易信号解析器。请分析用户输入的喊单信息，提取交易参数。

# ⚠️ 重要约束 (必须遵守!)
1. 下方"当前市场上下文"中的价格是**实时数据**，你必须使用这些数据进行分析。
2. **禁止使用你训练数据中的历史价格！禁止做任何价格估算！**
3. 如果用户提到的币种与上下文中的 symbol 不同，请在 warnings 中提示"无法获取该币种实时价格"。
4. 分析入场价格时，必须与上下文中的 current_price 对比，不要使用任何估算值。

# 系统交易规则 (重要!)
1. **净仓位模式**: 系统使用净仓位模式
   - 反向开仓 = 减仓/平仓 (不会报错)
   - 例: 持多0.5 BTC → 开空0.2 BTC = 平掉0.2多，剩0.3多
   - 例: 持多0.5 BTC → 开空0.8 BTC = 平掉多仓，反开0.3空
2. **加仓**: 同向开仓会合并仓位，使用加权平均价
3. **订单撮合**: 限价单满足条件时立即成交 (价格优于市价)

# 当前市场上下文
{context}

# 用户输入
{user_input}

# 任务
请将用户的喊单信息解析为结构化的交易参数。必须返回有效的 JSON 格式。

# 交易模式识别规则
1. **左侧交易 (Left Side)**:
   - 关键词: "挂单", "接多", "接空", "回踩", "反弹空", "limit"
   - 特征: 入场价优于当前价 (做多时入场价 < 当前价，做空时入场价 > 当前价)
   - 设置: trading_mode="left_side", entry_price=挂单价

2. **右侧交易 (Right Side)**:
   - 关键词: "突破", "breakout", "站稳", "确认", "追多", "追空"
   - 特征: 等待价格突破关键位
   - 设置: 
     - trading_mode="right_side"
     - trigger_price=突破价/压力位
     - confirm_interval="15m" (默认)
     - max_deviation_pct=0.5 (默认)

3. **市价交易 (Market)**:
   - 关键词: "现价", "立即", "market", "now"
   - 特征: 立即入场
   - 设置: trading_mode="market"

# ⚠️ 网格交易识别规则 (重要!)
如果用户输入包含以下关键词，必须设置 is_grid=true:
- "高抛低吸" / "低吸高抛" / "区间操作" / "震荡"
- "盘整" / "盘整区间" / "区间内"
- "网格" / "grid"
- 给出明确的上下限价格区间且建议反复操作

当 is_grid=true 时:
- grid_lower = 区间下限
- grid_upper = 区间上限  
- grid_direction = "neutral" (高抛低吸双向)
- side 可以忽略或设为 "long"
- grid_count = 建议 10-20 格

# 输出格式 (JSON)
{{
  "symbol": "BTCUSDT",
  "side": "long 或 short",
  "trading_mode": "left_side / right_side / market",
  
  // 左侧参数
  "entry_price": 数字或null,
  "entry_low": 入场区间下限或null,
  "entry_high": 入场区间上限或null,
  
  // 右侧参数
  "trigger_price": 突破触发价或null,
  "confirm_interval": "1m/5m/15m/30m/1h",
  "max_deviation_pct": 0.5,
  "timeout_hours": 24,

  "stop_loss": 止损价或null,
  "take_profit": 止盈价或null,
  "take_profit_levels": [多级止盈价格列表],
  "leverage": 杠杆倍数(默认5),
  "margin": 投入保证金金额或null,
  "position_percent": 仓位占比百分比或null,
  "ladder_enabled": 是否分批建仓(true/false),
  "ladder_count": 分批数量,
  "ladder_prices": [每批入场价],
  
  "is_grid": 是否网格交易(true/false),
  "grid_lower": 网格下限价,
  "grid_upper": 网格上限价,
  "grid_count": 网格数量(推荐10-20),
  "grid_type": "arithmetic"(等差)或"geometric"(等比),
  "grid_direction": "long"/"short"/"neutral",
  "grid_investment": 网格投资额,
  
  "confidence": 0-1之间的置信度,
  "reasoning": "你的分析推理过程",
  "warnings": ["可能的风险提示"]
}}

只返回 JSON，不要其他内容。"""


class AIBrain:
    """
    AI 大脑服务
    
    核心功能:
    1. 根据用户配置获取 AI Provider
    2. 构建完整上下文
    3. 解析喊单信号
    """
    
    @staticmethod
    async def get_provider(db: AsyncSession, user_id: int) -> BaseProvider:
        """
        获取用户配置的 AI Provider
        
        Args:
            db: 数据库会话
            user_id: 用户 ID
            
        Returns:
            配置好的 AI Provider
        """
        # 查询用户配置
        result = await db.execute(
            select(UserAIConfig).where(UserAIConfig.user_id == user_id)
        )
        config = result.scalar_one_or_none()
        
        if not config:
            # 使用默认 Ollama
            logger.info(f"[AIBrain] User {user_id} has no config, using default Ollama")
            return OllamaProvider()
        
        if config.provider == AIProvider.OLLAMA:
            return OllamaProvider(
                base_url=config.ollama_base_url or "http://localhost:11434",
                model=config.ollama_model or "deepseek-r1:14b",
            )
        
        elif config.provider in (AIProvider.DEEPSEEK, AIProvider.OPENAI):
            # 解密 API Key
            if not config.api_key_encrypted:
                raise ValueError("API Key not configured")
            
            api_key = decrypt_api_key(config.api_key_encrypted)
            
            return DeepSeekProvider(
                api_key=api_key,
                base_url=config.api_base_url or "https://api.deepseek.com",
                model=config.api_model or "deepseek-chat",
            )
        
        else:
            raise ValueError(f"Unsupported provider: {config.provider}")
    
    @staticmethod
    async def build_context(
        db: AsyncSession,
        user_id: int,
        symbol: str = "BTCUSDT",
    ) -> AIContext:
        """
        构建 AI 上下文
        
        收集用户的钱包、持仓、订单等信息
        """
        context = AIContext(timestamp=datetime.utcnow().isoformat())
        
        # 1. 获取市场数据
        try:
            from app.services.exchange import BinanceClient
            client = BinanceClient()
            ticker = await client.get_ticker(symbol)
            if ticker:
                context.market = MarketContext(
                    symbol=symbol,
                    current_price=float(ticker.get("lastPrice", 0)),
                    price_change_24h=float(ticker.get("priceChangePercent", 0)),
                    high_24h=float(ticker.get("highPrice", 0)),
                    low_24h=float(ticker.get("lowPrice", 0)),
                )
        except Exception as e:
            logger.warning(f"[AIBrain] Failed to get market data: {e}")
            # 使用默认值
            context.market = MarketContext(symbol=symbol, current_price=0)
        
        # 2. 获取钱包数据
        try:
            result = await db.execute(
                select(Wallet).where(Wallet.user_id == user_id)
            )
            wallet = result.scalar_one_or_none()
            if wallet:
                context.wallet = WalletContext(
                    balance=float(wallet.balance),
                    available=float(wallet.balance),  # available = balance (可用余额)
                    frozen=float(wallet.frozen),
                    equity=float(wallet.total_equity),  # total_equity property
                )
        except Exception as e:
            logger.warning(f"[AIBrain] Failed to get wallet: {e}")
        
        # 3. 获取持仓
        try:
            result = await db.execute(
                select(Position).where(
                    Position.user_id == user_id,
                    Position.status == PositionStatus.OPEN,
                )
            )
            positions = result.scalars().all()
            context.positions = [
                PositionContext(
                    symbol=p.symbol,
                    side=p.side.value,
                    size=float(p.size),
                    entry_price=float(p.entry_price),
                    unrealized_pnl=float(p.unrealized_pnl) if p.unrealized_pnl else 0,
                    leverage=p.leverage,
                )
                for p in positions
            ]
        except Exception as e:
            logger.warning(f"[AIBrain] Failed to get positions: {e}")
        
        # 4. 获取挂单数量
        try:
            result = await db.execute(
                select(Order).where(
                    Order.user_id == user_id,
                    Order.status.in_([OrderStatus.PENDING, OrderStatus.OPEN]),
                )
            )
            orders = result.scalars().all()
            context.pending_orders = len(orders)
        except Exception as e:
            logger.warning(f"[AIBrain] Failed to get orders: {e}")
        
        # 5. 获取运行中的网格
        try:
            result = await db.execute(
                select(GridBot).where(
                    GridBot.user_id == user_id,
                    GridBot.status == GridStatus.RUNNING,
                )
            )
            grids = result.scalars().all()
            context.running_grids = len(grids)
        except Exception as e:
            logger.warning(f"[AIBrain] Failed to get grids: {e}")
        
        # 6. 获取技术指标
        try:
            from app.services.indicator_service import indicator_service
            indicators = await indicator_service.get_or_calculate(symbol, "1h")
            context.indicators = indicators
            logger.debug(f"[AIBrain] Loaded indicators for {symbol}")
        except Exception as e:
            logger.warning(f"[AIBrain] Failed to get indicators: {e}")
        
        return context
    
    @staticmethod
    def _format_context(context: AIContext) -> str:
        """格式化上下文为文本"""
        lines = []
        
        if context.market:
            lines.append(f"## 市场数据 ({context.market.symbol})")
            lines.append(f"- 当前价格: ${context.market.current_price:,.2f}")
            lines.append(f"- 24h涨跌: {context.market.price_change_24h:+.2f}%")
            lines.append(f"- 24h高/低: ${context.market.high_24h:,.2f} / ${context.market.low_24h:,.2f}")
            lines.append("")
        
        if context.wallet:
            lines.append("## 账户资产")
            lines.append(f"- 总余额: ${context.wallet.balance:,.2f}")
            lines.append(f"- 可用: ${context.wallet.available:,.2f}")
            lines.append(f"- 冻结: ${context.wallet.frozen:,.2f}")
            lines.append("")
        
        if context.positions:
            lines.append("## 当前持仓")
            for p in context.positions:
                lines.append(f"- {p.symbol} {p.side.upper()} | 数量:{p.size} | 入场:{p.entry_price} | 杠杆:{p.leverage}x | 盈亏:{p.unrealized_pnl:+.2f}")
            lines.append("")
        else:
            lines.append("## 当前持仓: 无")
            lines.append("")
        
        lines.append(f"## 其他状态")
        lines.append(f"- 挂单数量: {context.pending_orders}")
        lines.append(f"- 运行中网格: {context.running_grids}")
        
        # 技术指标
        if context.indicators and context.indicators.get("indicators"):
            ind = context.indicators["indicators"]
            lines.append("")
            lines.append("## 技术指标")
            if ind.get("rsi"):
                rsi = ind["rsi"]
                status = "(超买)" if rsi > 70 else "(超卖)" if rsi < 30 else ""
                lines.append(f"- RSI(14): {rsi} {status}")
            if ind.get("ma7"):
                lines.append(f"- MA7: ${ind['ma7']:,.2f}")
            if ind.get("ma25"):
                lines.append(f"- MA25: ${ind['ma25']:,.2f}")
            if ind.get("atr"):
                lines.append(f"- ATR(14): ${ind['atr']:,.4f}")
            if context.indicators.get("trend"):
                trend_cn = {"bullish": "看涨", "bearish": "看跌", "neutral": "中性"}
                lines.append(f"- 趋势判断: {trend_cn.get(context.indicators['trend'], '未知')}")
        
        return "\n".join(lines)
    
    @staticmethod
    async def parse_signal(
        db: AsyncSession,
        user_id: int,
        text: str,
        symbol: Optional[str] = None,
    ) -> ParsedSignal:
        """
        解析喊单信号
        
        Args:
            db: 数据库会话
            user_id: 用户 ID
            text: 用户输入的喊单文本
            symbol: 可选指定币种
            
        Returns:
            解析后的结构化信号
        """
        # 1. 获取 AI Provider
        provider = await AIBrain.get_provider(db, user_id)
        
        # 2. 尝试从文本中提取币种
        detected_symbol = symbol
        if not detected_symbol:
            # 简单匹配常见币种
            text_upper = text.upper()
            for s in ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"]:
                if s.replace("USDT", "") in text_upper:
                    detected_symbol = s
                    break
            if not detected_symbol:
                detected_symbol = "BTCUSDT"
        
        # 3. 构建上下文
        context = await AIBrain.build_context(db, user_id, detected_symbol)
        context_text = AIBrain._format_context(context)
        
        # 4. 获取用户配置的系统提示词
        result = await db.execute(
            select(UserAIConfig).where(UserAIConfig.user_id == user_id)
        )
        config = result.scalar_one_or_none()
        system_prompt = config.system_prompt if config else "You are QuantaPro, a professional Crypto Quant Trader."
        
        # 5. 构建消息
        messages = [
            ChatMessage(role="system", content=system_prompt),
            ChatMessage(
                role="user",
                content=SIGNAL_PARSE_PROMPT.format(
                    context=context_text,
                    user_input=text,
                ),
            ),
        ]
        
        # 6. 调用 AI
        try:
            response = await provider.chat(messages, temperature=0.3)
            content = response.content
            
            # 7. 解析 JSON
            # 提取 JSON 部分 (处理可能的 markdown 代码块)
            json_match = re.search(r'```json\s*(.*?)\s*```', content, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                json_str = content.strip()
            
            # 移除可能的非 JSON 前缀
            if not json_str.startswith('{'):
                json_start = json_str.find('{')
                if json_start >= 0:
                    json_str = json_str[json_start:]
            
            data = json.loads(json_str)
            
            # 8. 构建 ParsedSignal
            # 8. 构建 ParsedSignal
            signal = ParsedSignal(
                symbol=data.get("symbol", detected_symbol),
                side=data.get("side", "long"),
                trade_style=data.get("trade_style", ""),
                
                # 交易模式
                trading_mode=data.get("trading_mode", "market"),
                trigger_price=data.get("trigger_price"),
                max_deviation_pct=data.get("max_deviation_pct", 0.5),
                confirm_interval=data.get("confirm_interval", "15m"),
                timeout_hours=data.get("timeout_hours", 24),
                
                entry_price=data.get("entry_price"),
                entry_low=data.get("entry_low"),
                entry_high=data.get("entry_high"),
                stop_loss=data.get("stop_loss"),
                take_profit=data.get("take_profit"),
                take_profit_levels=data.get("take_profit_levels", []),
                leverage=data.get("leverage", 5),
                margin=data.get("margin"),
                position_percent=data.get("position_percent"),
                ladder_enabled=data.get("ladder_enabled", False),
                ladder_count=data.get("ladder_count", 1),
                ladder_ratios=data.get("ladder_ratios", []),
                ladder_prices=data.get("ladder_prices", []),
                is_grid=data.get("is_grid", False),
                grid_lower=data.get("grid_lower"),
                grid_upper=data.get("grid_upper"),
                grid_count=data.get("grid_count"),
                grid_type=data.get("grid_type", "arithmetic"),
                grid_direction=data.get("grid_direction", "long"),
                grid_investment=data.get("grid_investment"),
                confidence=data.get("confidence", 0.5),
                reasoning=data.get("reasoning", ""),
                warnings=data.get("warnings", []),
            )
            
            # 9. 后处理验证
            signal = AIBrain._post_process_signal(signal, context)
            
            logger.info(f"[AIBrain] Parsed signal: {signal.symbol} {signal.side} @ {signal.entry_price}")
            return signal
            
        except json.JSONDecodeError as e:
            logger.error(f"[AIBrain] Failed to parse AI response as JSON: {e}")
            logger.debug(f"[AIBrain] Raw response: {content if 'content' in dir() else 'No response'}")
            raise ValueError("AI response is not valid JSON")
        except Exception as e:
            logger.error(f"[AIBrain] Parse signal failed: {e}")
            raise
    
    @staticmethod
    def _post_process_signal(signal: ParsedSignal, context: AIContext) -> ParsedSignal:
        """
        后处理信号
        
        验证和修正 AI 输出
        """
        # 确保币种格式正确
        if signal.symbol and not signal.symbol.endswith("USDT"):
            signal.symbol = signal.symbol.upper() + "USDT"
        
        # 如果 AI 没有返回入场价但有当前价格，使用当前价格
        if context.market and context.market.current_price > 0:
            current_price = context.market.current_price
            
            if signal.entry_price == 0 or signal.entry_price is None:
                if signal.entry_low and signal.entry_high:
                    signal.entry_price = (signal.entry_low + signal.entry_high) / 2
                else:
                    signal.entry_price = current_price
            
            # 验证止损合理性
            if signal.stop_loss:
                if signal.side == "long" and signal.stop_loss >= current_price:
                    signal.warnings.append("止损价高于当前价，多单止损应低于入场价")
                elif signal.side == "short" and signal.stop_loss <= current_price:
                    signal.warnings.append("止损价低于当前价，空单止损应高于入场价")
        
        # 确保杠杆在合理范围
        if signal.leverage < 1:
            signal.leverage = 1
        if signal.leverage > 125:
            signal.leverage = 125
        
        # 确保置信度在 0-1 之间
        if signal.confidence < 0:
            signal.confidence = 0
        if signal.confidence > 1:
            signal.confidence = 1
        
        return signal
    
    @staticmethod
    async def multi_analyze(
        db: AsyncSession,
        user_id: int,
        symbol: str = "BTCUSDT",
    ) -> Dict[str, Any]:
        """
        多智能体分析
        
        调用多个AI分析师从不同角度分析，最终由决策者汇总。
        """
        from app.core.config import settings as app_settings
        
        provider = await AIBrain.get_provider(db, user_id)
        context = await AIBrain.build_context(db, user_id, symbol)
        
        context_dict = {
            "market": {
                "current_price": context.market.current_price if context.market else 0,
                "price_change_24h": context.market.price_change_24h if context.market else 0,
                "high_24h": context.market.high_24h if context.market else 0,
                "low_24h": context.market.low_24h if context.market else 0,
                "volume_24h": 0,
            } if context.market else {},
            "wallet": {
                "balance": context.wallet.balance if context.wallet else 0,
                "available": context.wallet.available if context.wallet else 0,
                "frozen": context.wallet.frozen if context.wallet else 0,
            } if context.wallet else {},
            "positions": [
                {
                    "symbol": p.symbol,
                    "side": p.side,
                    "size": p.size,
                    "entry_price": p.entry_price,
                    "unrealized_pnl": p.unrealized_pnl,
                    "leverage": p.leverage,
                }
                for p in context.positions
            ],
            "indicators": context.indicators or {},
        }
        
        from .agents import MultiAgentOrchestrator
        
        orchestrator = MultiAgentOrchestrator(provider)
        result = await orchestrator.run(
            symbol=symbol,
            context=context_dict,
            debate_rounds=app_settings.multi_agent_debate_rounds,
        )
        
        return {
            "symbol": result.symbol,
            "final_recommendation": result.final_recommendation,
            "confidence": result.confidence,
            "final_decision": result.final_decision,
            "reasoning": result.reasoning,
            "warnings": result.warnings,
            "debate_rounds": result.debate_rounds,
            "reports": [
                {
                    "agent_name": r.agent_name,
                    "role": r.role,
                    "recommendation": r.recommendation,
                    "confidence": r.confidence,
                    "analysis": r.analysis,
                    "key_points": r.key_points,
                    "warnings": r.warnings,
                }
                for r in result.reports
            ],
        }
