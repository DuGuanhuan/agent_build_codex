"""
配置加载模块

从 YAML 文件加载模型配置，支持环境变量覆盖。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Optional, List, Dict

logger = logging.getLogger('agent.config')

# 尝试导入 YAML 解析器
try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False
    yaml = None


def _env_int(name: str, default: int) -> int:
    """从环境变量读取整数，失败则返回默认值"""
    value = os.getenv(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_str(name: str, default: Optional[str] = None) -> Optional[str]:
    """从环境变量读取字符串"""
    return os.getenv(name) or default


def _first_env_value(names: List[str]) -> Optional[str]:
    """返回第一个非空的环境变量值"""
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None


def _load_yaml_config() -> Dict[str, Any]:
    """加载 YAML 配置文件"""
    config_path = Path(__file__).parent / "models.yaml"
    
    if not config_path.exists():
        logger.warning(f"Config file not found: {config_path}")
        return {"models": [], "defaults": {}}
    
    if not YAML_AVAILABLE:
        logger.warning("PyYAML not installed, falling back to default config")
        return {"models": [], "defaults": {}}
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}
            logger.info(f"Loaded config from {config_path}")
            return data
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        return {"models": [], "defaults": {}}


def _resolve_model_config(model_def: Dict[str, Any]) -> Dict[str, Any]:
    """解析单个模型配置，应用环境变量覆盖"""
    config = {
        "id": model_def.get("id"),
        "label": model_def.get("label", model_def.get("id")),
        "provider": model_def.get("provider"),
        "description": model_def.get("description", ""),
    }
    
    # 模型名称（支持环境变量）
    if "model_env" in model_def:
        config["model"] = _env_str(model_def["model_env"], model_def.get("model_default", ""))
    else:
        config["model"] = model_def.get("model", "")
    
    # Base URL（支持多级环境变量回退）
    base_url = None
    if "base_url_env" in model_def:
        base_url = _env_str(model_def["base_url_env"])
    if not base_url and "base_url_fallback" in model_def:
        base_url = _env_str(model_def["base_url_fallback"])
    if not base_url:
        base_url = model_def.get("base_url_default", "")
    config["base_url"] = base_url
    
    # API Key 环境变量列表
    config["api_key_envs"] = model_def.get("api_key_envs", [])
    
    # 思考模式
    thinking = model_def.get("thinking", "disabled")
    if thinking:
        config["thinking"] = {"type": thinking}
    
    # 推理强度
    if model_def.get("reasoning_effort"):
        config["reasoning_effort"] = model_def["reasoning_effort"]
    
    # 上下文窗口（支持环境变量覆盖）
    if "context_window_tokens_env" in model_def:
        config["context_window_tokens"] = _env_int(
            model_def["context_window_tokens_env"],
            model_def.get("context_window_tokens", 128000)
        )
    else:
        config["context_window_tokens"] = model_def.get("context_window_tokens", 128000)
    
    # 最大输出 tokens（支持环境变量覆盖）
    if "max_output_tokens_env" in model_def:
        config["max_output_tokens"] = _env_int(
            model_def["max_output_tokens_env"],
            model_def.get("max_output_tokens_default", 2048)
        )
    else:
        config["max_output_tokens"] = model_def.get("max_output_tokens", 2048)
    
    return config


def load_model_options() -> tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """
    加载模型配置选项
    
    Returns:
        (model_options, model_options_by_id)
    """
    config = _load_yaml_config()
    models = config.get("models", [])
    defaults = config.get("defaults", {})
    
    # 解析全局默认值（环境变量优先）
    llm_max_tokens = _env_int(
        defaults.get("llm_max_tokens_env", "LLM_MAX_TOKENS"),
        defaults.get("llm_max_tokens", 2048)
    )
    default_model_id = _env_str(
        defaults.get("default_model_id_env", "DEFAULT_MODEL_ID"),
        defaults.get("default_model_id", "zhipu-glm-4.7-flash")
    )
    
    # 如果 YAML 配置为空，使用内置默认配置（向后兼容）
    if not models:
        logger.info("Using built-in default model configuration")
        return _get_builtin_model_options()
    
    # 解析模型配置
    model_options = []
    for model_def in models:
        try:
            config = _resolve_model_config(model_def)
            model_options.append(config)
        except Exception as e:
            logger.error(f"Failed to resolve model config {model_def.get('id')}: {e}")
    
    model_options_by_id = {m["id"]: m for m in model_options}
    
    # 注入全局默认值
    for model in model_options:
        model["_llm_max_tokens"] = llm_max_tokens
        model["_is_default"] = model["id"] == default_model_id
    
    return model_options, model_options_by_id


def _get_builtin_model_options() -> tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """
    内置默认模型配置（当 YAML 不可用时使用）
    这是从 server.py 迁移的原始配置，确保向后兼容
    """
    llm_max_tokens = _env_int("LLM_MAX_TOKENS", 2048)
    default_context_window = _env_int("DEFAULT_CONTEXT_WINDOW_TOKENS", 128000)
    
    model_options = [
        {
            "id": "zhipu-glm-4.7-flash",
            "label": "智谱 GLM-4.7-Flash",
            "provider": "zhipu",
            "model": "glm-4.7-flash",
            "base_url": _env_str("ZHIPU_BASE_URL") or _env_str("ZAI_BASE_URL") or "https://open.bigmodel.cn/api/paas/v4",
            "api_key_envs": ["ZAI_API_KEY", "ZHIPU_API_KEY"],
            "thinking": "disabled",
            "context_window_tokens": _env_int("ZHIPU_CONTEXT_WINDOW_TOKENS", 200000),
            "max_output_tokens": 128000,
            "description": "免费/快速，适合日常聊天和这个轻量 Agent demo。",
        },
        {
            "id": "deepseek-v4-flash",
            "label": "DeepSeek V4 Flash",
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "base_url": _env_str("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            "api_key_envs": ["DEEPSEEK_API_KEY"],
            "thinking": "disabled",
            "context_window_tokens": _env_int("DEEPSEEK_CONTEXT_WINDOW_TOKENS", 1000000),
            "max_output_tokens": 384000,
            "description": "低成本、低延迟，推荐作为 DeepSeek 默认选项。",
        },
        {
            "id": "wanqing-kimi-k2.5",
            "label": "万擎 Kimi K2.5",
            "provider": "wanqing",
            "model": _env_str("WQ_MODEL", "ep-cvhcjv-1776239525862887187"),
            "base_url": _env_str("WQ_BASE_URL") or _env_str("WANQING_BASE_URL") or "http://wanqing.internal/api/gateway/v1/endpoints",
            "api_key_envs": ["WQ_API_KEY"],
            "context_window_tokens": _env_int("WQ_CONTEXT_WINDOW_TOKENS", default_context_window),
            "max_output_tokens": _env_int("WQ_MAX_OUTPUT_TOKENS", llm_max_tokens),
            "description": "公司内部万擎部署的 Kimi K2.5 推理接入点。",
        },
        {
            "id": "deepseek-v4-pro",
            "label": "DeepSeek V4 Pro",
            "provider": "deepseek",
            "model": "deepseek-v4-pro",
            "base_url": _env_str("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            "api_key_envs": ["DEEPSEEK_API_KEY"],
            "thinking": "disabled",
            "context_window_tokens": _env_int("DEEPSEEK_CONTEXT_WINDOW_TOKENS", 1000000),
            "max_output_tokens": 384000,
            "description": "质量更高，适合复杂一点的问答和 Agent 规划。",
        },
        {
            "id": "deepseek-v4-pro-thinking",
            "label": "DeepSeek V4 Pro Thinking",
            "provider": "deepseek",
            "model": "deepseek-v4-pro",
            "base_url": _env_str("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            "api_key_envs": ["DEEPSEEK_API_KEY"],
            "thinking": {"type": "enabled"},
            "reasoning_effort": "high",
            "context_window_tokens": _env_int("DEEPSEEK_CONTEXT_WINDOW_TOKENS", 1000000),
            "max_output_tokens": 384000,
            "description": "开启思考模式，适合更难的问题；会更慢、更贵。",
        },
        {
            "id": "mimo-v2.5-pro",
            "label": "小米 MiMo V2.5 Pro",
            "provider": "xiaomi",
            "model": "mimo-v2.5-pro",
            "base_url": _env_str("MIMO_BASE_URL", "https://token-plan-sgp.xiaomimimo.com/v1"),
            "api_key_envs": ["MIMO_API_KEY"],
            "thinking": "disabled",
            "context_window_tokens": _env_int("MIMO_CONTEXT_WINDOW_TOKENS", 128000),
            "max_output_tokens": 4096,
            "description": "小米 MiMo 旗舰模型，性能强劲，适合各类复杂任务。",
        },
        {
            "id": "mimo-v2.5",
            "label": "小米 MiMo V2.5",
            "provider": "xiaomi",
            "model": "mimo-v2.5",
            "base_url": _env_str("MIMO_BASE_URL", "https://token-plan-sgp.xiaomimimo.com/v1"),
            "api_key_envs": ["MIMO_API_KEY"],
            "thinking": "disabled",
            "context_window_tokens": _env_int("MIMO_CONTEXT_WINDOW_TOKENS", 128000),
            "max_output_tokens": 4096,
            "description": "小米 MiMo 快速模型，响应迅速。",
        },
    ]
    
    model_options_by_id = {option["id"]: option for option in model_options}
    return model_options, model_options_by_id
