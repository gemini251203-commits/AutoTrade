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


async def _get_user_api_configs(user_id: int) -> dict:
    """
    获取用于 mem0 的 API 配置。
    
    策略:
    - LLM: 优先 DeepSeek（稳定可靠，用户已有 key）
    - Embedder: 优先 Gemini（embedding 免费额度极高 1500次/分钟）
    
    返回 {"llm": {...}, "embedder": {...}} 或空字典
    """
    llm_cfg = {}
    embedder_cfg = {}
    gemini_key = ""
    deepseek_key = ""
    deepseek_base = ""
    deepseek_model = ""
    
    # 1. 从数据库读取用户的 AI 配置
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
                
                if "googleapis.com" in base_url or "gemini" in model.lower():
                    gemini_key = api_key
                else:
                    deepseek_key = api_key
                    deepseek_base = base_url or "https://api.deepseek.com"
                    deepseek_model = model
    except Exception as e:
        logger.debug(f"[MemoryService] Failed to load user config from DB: {e}")
    
    # 2. 从 Hub Agent 获取 DeepSeek key（用户的 Agent 通常配了 DeepSeek）
    if not deepseek_key:
        try:
            from app.db.session import AsyncSessionLocal
            from app.models.hub_agent import HubAgent
            from app.core.encryption import decrypt_api_key
            from sqlalchemy import select
            
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(HubAgent).where(
                        HubAgent.user_id == user_id,
                        HubAgent.api_key_enc.isnot(None),
                        HubAgent.api_key_enc != '',
                    ).limit(1)
                )
                agent = result.scalar_one_or_none()
                if agent and agent.api_key_enc:
                    # Hub Agent 用 _decrypt_key 解密（不同于 UserAIConfig 的 decrypt_api_key）
                    try:
                        from app.api.hub import _decrypt_key
                        agent_key = _decrypt_key(agent.api_key_enc)
                    except Exception:
                        # fallback: 尝试另一种解密方式
                        agent_key = decrypt_api_key(agent.api_key_enc)
                    agent_base = agent.api_base_url or ""
                    agent_model = agent.model or ""
                    logger.info(
                        f"[MemoryService] Found Hub Agent #{agent.id} '{agent.name}': "
                        f"model={agent_model}, base_url={agent_base[:30]}..."
                    )
                    # 非 Gemini 的 Agent key 可用作 DeepSeek LLM
                    if "googleapis.com" not in agent_base and "gemini" not in agent_model.lower():
                        deepseek_key = agent_key
                        deepseek_base = agent_base or "https://api.deepseek.com"
                        deepseek_model = agent_model or "deepseek-chat"
                        logger.info(f"[MemoryService] → Using as DeepSeek LLM ({deepseek_model})")
                    elif not gemini_key:
                        gemini_key = agent_key
                        logger.info("[MemoryService] → Using as Gemini key")
                    else:
                        logger.info("[MemoryService] → Skipped (already have gemini key)")
                else:
                    logger.info(f"[MemoryService] No Hub Agent with API key for user {user_id}")
        except Exception as e:
            logger.warning(f"[MemoryService] Failed to load Hub Agent key: {e}")
    
    # 3. 环境变量补充
    if not gemini_key:
        gemini_key = os.environ.get("GEMINI_API_KEY", "")
    if not deepseek_key:
        deepseek_key = os.environ.get("OPENAI_API_KEY", "")
        if deepseek_key and not deepseek_base:
            deepseek_base = "https://api.deepseek.com"
            deepseek_model = "deepseek-chat"
    
    # 3. 组装配置 — LLM 优先 DeepSeek，Embedder 优先 Gemini
    
    # Embedder: Gemini text-embedding-004（免费额度极高）
    if gemini_key:
        embedder_cfg = {
            "provider": "gemini",
            "config": {
                "api_key": gemini_key,
                "model": "gemini-embedding-001",
                "embedding_dims": 768,
            },
        }
    
    # LLM: DeepSeek（稳定，避免 Gemini 速率限制）
    if deepseek_key:
        llm_cfg = {
            "provider": "openai",
            "config": {
                "api_key": deepseek_key,
                "model": deepseek_model or "deepseek-chat",
                "openai_base_url": deepseek_base or "https://api.deepseek.com",
            },
        }
    elif gemini_key:
        # 没有 DeepSeek 时 fallback 到 Gemini
        llm_cfg = {
            "provider": "gemini",
            "config": {
                "api_key": gemini_key,
                "model": "gemini-2.0-flash",
            },
        }
    
    # 如果没有 Gemini 做 embedder，但有 DeepSeek → 用 OpenAI 兼容 embedding
    if not embedder_cfg and deepseek_key:
        embedder_cfg = {
            "provider": "openai",
            "config": {
                "api_key": deepseek_key,
                "model": "text-embedding-3-small",
                "openai_base_url": deepseek_base,
            },
        }
    
    if llm_cfg and embedder_cfg:
        return {"llm": llm_cfg, "embedder": embedder_cfg}
    
    return {}


async def get_memory(user_id: int):
    """
    获取 mem0 Memory 实例（按 user_id 缓存）。
    
    架构:
    - LLM: DeepSeek（稳定，fact extraction）
    - Embedder: Gemini text-embedding-004（免费额度高）
    - Vector Store: Qdrant on-disk
    """
    global _memory_instances, _init_failures
    
    if user_id in _memory_instances:
        return _memory_instances[user_id]
    
    if user_id in _init_failures:
        return None
    
    try:
        from mem0 import Memory
        
        # 获取 LLM + Embedder 配置
        api_cfgs = await _get_user_api_configs(user_id)
        
        if not api_cfgs:
            logger.warning(
                f"[MemoryService] No API key available for user {user_id}. "
                "Need at least one of: Gemini API key or DeepSeek API key. "
                "Memory service disabled for this user."
            )
            _init_failures.add(user_id)
            return None
        
        # 确定 embedding 维度
        embedder_provider = api_cfgs["embedder"]["provider"]
        embedding_dims = 768 if embedder_provider == "gemini" else 1536
        
        config = {
            "vector_store": {
                "provider": "qdrant",
                "config": {
                    "collection_name": f"user_{user_id}_memories",
                    "path": LANCEDB_PATH,
                    "embedding_model_dims": embedding_dims,
                    "on_disk": True,
                },
            },
            "embedder": api_cfgs["embedder"],
            "llm": api_cfgs["llm"],
        }
        
        llm_provider = api_cfgs["llm"]["provider"]
        llm_model = api_cfgs["llm"]["config"].get("model", "unknown")
        emb_model = api_cfgs["embedder"]["config"].get("model", "unknown")
        
        import asyncio
        instance = await asyncio.to_thread(Memory.from_config, config)
        _memory_instances[user_id] = instance
        logger.info(
            f"[MemoryService] Initialized for user {user_id}: "
            f"LLM={llm_provider}/{llm_model}, Embedder={embedder_provider}/{emb_model}"
        )
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
