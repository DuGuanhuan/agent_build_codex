"""
统一异常定义模块

为项目提供清晰的异常层次结构，便于错误处理和调试。
"""

from typing import Optional


class AgentError(Exception):
    """Agent 基础异常类"""
    
    def __init__(self, message: str, cause: Optional[Exception] = None):
        self.message = message
        self.cause = cause
        super().__init__(message)
    
    def __str__(self) -> str:
        if self.cause:
            return f"{self.message} (caused by: {self.cause})"
        return self.message


# ==================== 配置相关异常 ====================

class ConfigurationError(AgentError):
    """配置错误：环境变量缺失、配置格式错误等"""
    pass


class ModelNotFoundError(ConfigurationError):
    """模型未找到或不可用"""
    pass


class RuntimeNotAvailableError(ConfigurationError):
    """Runtime 不可用"""
    pass


# ==================== 技能相关异常 ====================

class SkillError(AgentError):
    """技能相关错误基类"""
    pass


class SkillLoadError(SkillError):
    """技能加载失败"""
    pass


class SkillExecutionError(SkillError):
    """技能执行失败"""
    pass


class SkillNotFoundError(SkillError):
    """技能不存在"""
    pass


# ==================== LLM 相关异常 ====================

class LLMError(AgentError):
    """LLM 调用相关错误基类"""
    pass


class LLMConnectionError(LLMError):
    """LLM 连接错误：网络问题、服务不可达等"""
    pass


class LLMRateLimitError(LLMError):
    """LLM 速率限制错误"""
    pass


class LLMAuthenticationError(LLMError):
    """LLM 认证错误：API Key 无效等"""
    pass


class LLMResponseError(LLMError):
    """LLM 响应错误：解析失败、格式异常等"""
    pass


# ==================== Turn 相关异常 ====================

class TurnError(AgentError):
    """Turn 相关错误基类"""
    pass


class TurnNotFoundError(TurnError):
    """Turn 不存在"""
    pass


class TurnStateError(TurnError):
    """Turn 状态错误：尝试对已回滚的 turn 操作等"""
    pass


# ==================== 工具相关异常 ====================

class ToolError(AgentError):
    """工具相关错误基类"""
    pass


class ToolExecutionError(ToolError):
    """工具执行失败"""
    pass


class ToolPermissionDeniedError(ToolError):
    """工具权限被拒绝"""
    pass


class ToolTimeoutError(ToolError):
    """工具执行超时"""
    pass


# ==================== 验证相关异常 ====================

class ValidationError(AgentError):
    """输入验证错误"""
    pass


class MessageValidationError(ValidationError):
    """消息格式验证错误"""
    pass


# ==================== 存储/IO 相关异常 ====================

class StorageError(AgentError):
    """存储相关错误基类"""
    pass


class FileOperationError(StorageError):
    """文件操作错误：读写失败、权限问题等"""
    pass


class DataCorruptionError(StorageError):
    """数据损坏错误：hash 校验失败等"""
    pass
