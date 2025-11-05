# module/config_loader.py
"""
配置模块：统一管理配置读取
"""
import os
import toml
from typing import Dict, Any, Optional
from pathlib import Path
from loguru import logger


class ConfigLoader:
    """配置加载器：负责读取和管理配置文件"""
    
    def __init__(self, env: Optional[str] = None):
        """
        :param env: 环境名称，如 'local', 'dev', 'sit', 'prd'。如果为None，从环境变量读取
        """
        if env is None:
            env = os.environ.get('APP_ENV', 'local')
        self.env = env
        self.config_path = Path(f'./config/{env}.toml')
        self._config: Dict[str, Any] = {}
        self.load_config()
    
    def load_config(self):
        """加载配置文件"""
        if not self.config_path.exists():
            raise FileNotFoundError(f"配置文件不存在: {self.config_path}")
        self._config = toml.load(self.config_path)
        logger.info(f"已加载配置文件: {self.config_path}")
    
    def get(self, key: str, default: Any = None) -> Any:
        """获取配置值，支持点号分隔的嵌套key，如 'static.common-file-center.host'"""
        keys = key.split('.')
        value = self._config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
                if value is None:
                    return default
            else:
                return default
        return value
    
    def get_file_center_config(self) -> Dict[str, Any]:
        """获取文件中心配置"""
        return {
            'host': self.get('static.common-file-center.host'),
            'port': self.get('static.common-file-center.port')
        }
    
    def get_callback_config(self) -> Dict[str, Any]:
        """获取回调服务配置"""
        return {
            'host': self.get('static.app-ai-center-service.host'),
            'port': self.get('static.app-ai-center-service.port'),
            'final_result_path': self.get('callback.final_result_path'),
            'ocr_result_path': self.get('callback.ocr_result_path')
        }
    
    def get_openai_config(self) -> Dict[str, Any]:
        """获取OpenAI/LLM配置"""
        return self.get('openai', {})
    
    def get_tokenizer_config(self) -> Dict[str, Any]:
        """获取tokenizer配置"""
        return self.get('tokenizer', {})
    
    def get_app_config(self) -> Dict[str, Any]:
        """获取应用配置"""
        return self.get('app', {})
    
    def get_ocrvl_config(self) -> Dict[str, Any]:
        """获取OCR-VL配置"""
        return self.get('ocrvl', {})
    
    @property
    def config(self) -> Dict[str, Any]:
        """获取完整配置字典"""
        return self._config

