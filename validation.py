"""
API 输入验证模块

使用 Pydantic 模型集中验证前端请求，确保输入格式正确。
"""

from typing import Any, Literal, Optional

try:
    from pydantic import BaseModel, Field, field_validator
    PYDANTIC_AVAILABLE = True
except ImportError:
    PYDANTIC_AVAILABLE = False
    # 如果 Pydantic 不可用，提供简单的替代实现
    BaseModel = object
    def Field(*args, **kwargs):
        return None
    def field_validator(*args, **kwargs):
        def decorator(func):
            return func
        return decorator


if PYDANTIC_AVAILABLE:
    class ChatRequest(BaseModel):
        """聊天请求验证"""
        messages: list[dict[str, Any]] = Field(..., max_length=80)
        model: Optional[str] = None
        runtime: Optional[str] = None
        session_id: Optional[str] = None
        trusted_tools: list[str] = Field(default_factory=list)
        
        @field_validator('messages')
        @classmethod
        def validate_messages(cls, v):
            if not isinstance(v, list):
                raise ValueError('messages 必须是数组')
            for i, msg in enumerate(v):
                if not isinstance(msg, dict):
                    raise ValueError(f'messages[{i}] 必须是对象')
                if 'role' not in msg:
                    raise ValueError(f'messages[{i}] 缺少 role 字段')
                if msg['role'] not in ('user', 'assistant', 'system'):
                    raise ValueError(f'messages[{i}].role 必须是 user/assistant/system')
                if 'content' not in msg:
                    raise ValueError(f'messages[{i}] 缺少 content 字段')
                if not isinstance(msg['content'], str):
                    raise ValueError(f'messages[{i}].content 必须是字符串')
            return v
        
        @field_validator('trusted_tools')
        @classmethod
        def validate_trusted_tools(cls, v):
            if not isinstance(v, list):
                raise ValueError('trusted_tools 必须是数组')
            for tool in v:
                if not isinstance(tool, str):
                    raise ValueError('trusted_tools 中的元素必须是字符串')
            return v


    class RetryTurnRequest(BaseModel):
        """重试 Turn 请求验证"""
        turn_id: str = Field(..., min_length=1)
        edited_content: Optional[str] = None


    class SummarizeRequest(BaseModel):
        """摘要请求验证"""
        messages: list[dict[str, Any]] = Field(..., max_length=100)
        model: Optional[str] = None
        summary: str = Field(default="")
        
        @field_validator('messages')
        @classmethod
        def validate_messages(cls, v):
            if not isinstance(v, list):
                raise ValueError('messages 必须是数组')
            return v


    class ContextEstimateRequest(BaseModel):
        """上下文估算请求验证"""
        messages: list[dict[str, Any]] = Field(..., max_length=100)
        model: Optional[str] = None
        
        @field_validator('messages')
        @classmethod
        def validate_messages(cls, v):
            if not isinstance(v, list):
                raise ValueError('messages 必须是数组')
            return v


    class SkillSaveRequest(BaseModel):
        """技能保存请求验证"""
        name: str = Field(..., min_length=1, max_length=64)
        meta: dict[str, Any] = Field(default_factory=dict)
        instructions: str = Field(default="")
        
        @field_validator('name')
        @classmethod
        def validate_name(cls, v):
            if not v.replace('_', '').replace('-', '').isalnum():
                raise ValueError('name 只能包含字母、数字、下划线和连字符')
            return v


    class SkillDeleteRequest(BaseModel):
        """技能删除请求验证"""
        name: str = Field(..., min_length=1)


    class RuntimeAbortRequest(BaseModel):
        """Runtime 中止请求验证"""
        runtime: Optional[str] = None
        session_id: str = Field(..., min_length=1)


    class RuntimeArtifactsRequest(BaseModel):
        """Runtime artifacts 请求验证"""
        runtime: Optional[str] = None
        session_id: str = Field(..., min_length=1)

else:
    # Pydantic 不可用时的简单验证函数
    def validate_messages(messages: Any) -> list[dict[str, Any]]:
        if not isinstance(messages, list):
            raise ValueError('messages 必须是数组')
        if len(messages) > 80:
            raise ValueError('messages 长度不能超过 80')
        for i, msg in enumerate(messages):
            if not isinstance(msg, dict):
                raise ValueError(f'messages[{i}] 必须是对象')
            if 'role' not in msg:
                raise ValueError(f'messages[{i}] 缺少 role 字段')
            if 'content' not in msg:
                raise ValueError(f'messages[{i}] 缺少 content 字段')
        return messages
    
    ChatRequest = None
    RetryTurnRequest = None
    SummarizeRequest = None
    ContextEstimateRequest = None
    SkillSaveRequest = None
    SkillDeleteRequest = None
    RuntimeAbortRequest = None
    RuntimeArtifactsRequest = None


def validate_chat_request(data: dict[str, Any]) -> dict[str, Any]:
    """验证聊天请求"""
    if PYDANTIC_AVAILABLE:
        return ChatRequest(**data).model_dump()
    else:
        messages = validate_messages(data.get('messages', []))
        return {
            'messages': messages,
            'model': data.get('model'),
            'runtime': data.get('runtime'),
            'session_id': data.get('session_id'),
            'trusted_tools': data.get('trusted_tools', []),
        }
