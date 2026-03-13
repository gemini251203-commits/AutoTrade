"""
Memory Service — 向量化长期记忆
===================================
基于 mem0 + LanceDB 的语义记忆系统。

职责:
1. 将 board_minutes 纪要向量化存入 LanceDB
2. 语义搜索相关历史记忆
3. 为 Agent 巡逻提供"深层记忆"上下文

架构:
  board_minutes → mem0.add() → LanceDB (embedding 存储)
  Agent 巡逻 → mem0.search() → 语义匹配的历史记忆
"""

import os
from typing import Optional, List, Dict, Any

from loguru import logger


# LanceDB 数据存储路径
LANCEDB_PATH = os.environ.get("LANCEDB_PATH", "/app/lancedb_data")

# 全局单例 (按 user_id 缓存)
_memory_instances: Dict[int, Any] = {}
_init_failures: set = set()  # 初始化失败的 user_id，避免重复尝试


async def _get_user_gemini_key(user_id: int) -> dict:
    """
    从数据库获取用户的 Gemini API 配置。
    优先级: 环境变量 GEMINI_API_KEY > UserAIConfig 表中的 Gemini 配置
    """
    # 1. 优先使用环境变量
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    if gemini_key:
        return {
            "api_key": gemini_key,
            "model": "gemini-2.0-flash",
            "embedding_model": "models/text-embedding-004",
        }
    
    # 2. 从数据库读取用户的 AI 配置
    try:
        from app.db.session import AsyncSessionLocal
        from app.models.user_ai_config import UserAIConfig
        from app.core.encryption import decrypt_api_key
        from sqlalchemy import select

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(UserAIConfig).where(UserAIConfig.user_id == user_id)
            )
            cfg = result.scalar_one_or_none()
            if cfg and cfg.api_key_encrypted:
                api_key = decrypt_api_key(cfg.api_key_encrypted)
                base_url = cfg.api_base_url or ""
                model = cfg.model or "deepseek-chat"
                
                # 检测是否是 Gemini
                if "googleapis.com" in base_url or "gemini" in model.lower():
                    return {
                        "api_key": api_key,
                        "model": model,
                        "embedding_model": "models/text-embedding-004",
                        "provider": "gemini",
                    }
                
                # 非 Gemini (DeepSeek 等)，也可以尝试用 OpenAI 兼容模式
                return {
                    "api_key": api_key,
                    "model": model,
                    "base_url": base_url,
                    "provider": "openai_compatible",
                }
    except Exception as e:
        logger.debug(f"[MemoryService] Failed to load user config: {e}")
    
    return {}


async def get_memory(user_id: int):
    """
    获取 mem0 Memory 实例（按 user_id 缓存）。
    
    使用 Gemini 做 embedding + fact extraction，Qdrant on-disk 做向量存储。
    如果初始化失败（缺少 API key 等），返回 None。
    """
    global _memory_instances, _init_failures
    
    if user_id in _memory_instances:
        return _memory_instances[user_id]
    
    if user_id in _init_failures:
        return None  # 已尝试过但失败了
    
    try:
        from mem0 import Memory
        
        config = {
            "vector_store": {
                "provider": "qdrant",
                "config": {
                    "collection_name": f"user_{user_id}_memories",
                    "path": LANCEDB_PATH,  # Qdrant on-disk 存储路径
                    "embedding_model_dims": 768,
                    "on_disk": True,
                },
            },
        }
        
        # 获取用户 API 配置
        api_cfg = await _get_user_gemini_key(user_id)
        
        if api_cfg.get("provider") == "gemini" or "googleapis" in api_cfg.get("base_url", ""):
            config["embedder"] = {
                "provider": "gemini",
                "config": {
                    "api_key": api_cfg["api_key"],
                    "model": api_cfg.get("embedding_model", "models/text-embedding-004"),
                    "embedding_dims": 768,
                },
            }
            config["llm"] = {
                "provider": "gemini",
                "config": {
                    "api_key": api_cfg["api_key"],
                    "model": api_cfg.get("model", "gemini-2.0-flash"),
                },
            }
        elif api_cfg.get("api_key"):
            # OpenAI 兼容模式 (DeepSeek 等)
            embedder_cfg = {
                "api_key": api_cfg["api_key"],
                "model": "text-embedding-3-small",
            }
            if api_cfg.get("base_url"):
                embedder_cfg["openai_base_url"] = api_cfg["base_url"]
            
            config["embedder"] = {
                "provider": "openai",
                "config": embedder_cfg,
            }
            config["llm"] = {
                "provider": "openai",
                "config": {
                    "api_key": api_cfg["api_key"],
                    "model": api_cfg.get("model", "deepseek-chat"),
                    "openai_base_url": api_cfg.get("base_url", "https://api.deepseek.com"),
                },
            }
        else:
            logger.warning(
                f"[MemoryService] No API key available for user {user_id}. "
                "Set GEMINI_API_KEY env var or configure AI in settings. "
                "Memory service disabled for this user."
            )
            _init_failures.add(user_id)
            return None
        
        import asyncio
        instance = await asyncio.to_thread(Memory.from_config, config)
        _memory_instances[user_id] = instance
        logger.info(f"[MemoryService] Initialized for user {user_id} with LanceDB at {LANCEDB_PATH}")
        return instance
    
    except Exception as e:
        logger.error(f"[MemoryService] Failed to initialize for user {user_id}: {e}")
        _init_failures.add(user_id)
        return None


async def add_board_minutes_memory(
    user_id: int,
    date_str: str,
    summary: str,
    key_lessons: str,
    trade_count: int = 0,
    pnl_total: float = 0.0,
) -> bool:
    """
    将 board_minutes 纪要存入 mem0 向量化记忆。
    
    在 consolidator 生成纪要后调用。
    mem0 会自动提取关键 facts 并向量化存储。
    """
    m = await get_memory(user_id)
    if m is None:
        return False
    
    try:
        # 构建记忆文本
        pnl_sign = "+" if pnl_total >= 0 else ""
        memory_text = (
            f"[{date_str} 交易日复盘]\n"
            f"交易 {trade_count} 笔，盈亏 {pnl_sign}{pnl_total:.1f} USDT。\n"
            f"摘要: {summary[:500]}\n"
            f"教训: {key_lessons[:200]}"
        )
        
        messages = [
            {"role": "user", "content": memory_text},
        ]
        
        # mem0 是同步的，需要在线程中运行
        import asyncio
        result = await asyncio.to_thread(
            m.add,
            messages,
            user_id=str(user_id),
            metadata={"type": "board_minutes", "date": date_str},
        )
        
        results_count = len(result.get("results", [])) if isinstance(result, dict) else 0
        logger.info(
            f"[MemoryService] Added board minutes for user {user_id}, "
            f"date {date_str}: {results_count} facts extracted"
        )
        return True
    
    except Exception as e:
        logger.error(f"[MemoryService] Failed to add memory: {e}")
        return False


async def search_memories(
    user_id: int,
    query: str,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """
    语义搜索用户的历史记忆。
    """
    m = await get_memory(user_id)
    if m is None:
        return []
    
    try:
        import asyncio
        result = await asyncio.to_thread(
            m.search,
            query,
            user_id=str(user_id),
            limit=limit,
        )
        
        memories = result.get("results", []) if isinstance(result, dict) else []
        logger.info(
            f"[MemoryService] Search '{query[:30]}...' for user {user_id}: "
            f"{len(memories)} results"
        )
        return memories
    
    except Exception as e:
        logger.error(f"[MemoryService] Search failed: {e}")
        return []


async def get_relevant_context(
    user_id: int,
    current_situation: str,
    limit: int = 3,
) -> str:
    """
    获取与当前情况相关的历史记忆上下文。
    
    供 brain.py 在 Agent 巡逻时调用，注入到 system prompt。
    """
    memories = await search_memories(user_id, current_situation, limit=limit)
    
    if not memories:
        return ""
    
    lines = ["## 深层记忆（语义匹配的历史经验）"]
    for i, mem in enumerate(memories, 1):
        memory_text = mem.get("memory", "")
        score = mem.get("score", 0)
        if memory_text:
            lines.append(f"{i}. [相关度:{score:.0%}] {memory_text}")
    
    return "\n".join(lines)
