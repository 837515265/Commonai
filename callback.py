# module/callback.py
"""
回调模块：处理结果回调逻辑
"""
import time
import requests
from loguru import logger
from typing import Optional

log_name = 'callback'
logger.add(
    f"logs/module_{log_name}_{{time:YYYY-MM-DD}}.log",
    level="INFO",
    rotation="00:00",
    filter=lambda record: record["extra"].get("name") == log_name,
    enqueue=False,
    buffering=1
)
callback_logger = logger.bind(name=log_name)


class CallbackClient:
    """回调客户端：负责向外部服务发送结果"""
    
    def __init__(self, callback_host: str, callback_port: int, final_result_path: str, ocr_result_path: str):
        """
        :param callback_host: 回调服务主机地址
        :param callback_port: 回调服务端口
        :param final_result_path: 最终结果回调路径
        :param ocr_result_path: OCR结果回调路径
        """
        self.callback_host = callback_host
        self.callback_port = callback_port
        self.final_result_url = f'http://{callback_host}:{callback_port}{final_result_path}'
        self.ocr_result_url = f'http://{callback_host}:{callback_port}{ocr_result_path}'
    
    def send_error_result(self, task_no: str, error_msg: str, retry_count: int = 3, retry_delay: int = 3):
        """发送错误结果"""
        error_data = {"taskNo": task_no, "errorMsg": error_msg}
        try:
            for _ in range(retry_count):
                resp = requests.post(self.final_result_url, json=error_data)
                if resp.status_code == 200:
                    callback_logger.info(f'{task_no}：错误消息已返回')
                    break
                else:
                    callback_logger.warning(f'{task_no}：错误消息返回失败，重试中...')
                    time.sleep(retry_delay)
        except Exception as e:
            callback_logger.error(f'{task_no}：错误消息返回失败: {e}')
    
    def send_normal_result(self, task_no: str, result: str, retry_count: int = 3, retry_delay: int = 3):
        """发送正常结果"""
        data = {"taskNo": task_no, "result": result}
        try:
            for _ in range(retry_count):
                resp = requests.post(self.final_result_url, json=data)
                if resp.status_code == 200:
                    callback_logger.info(f'{task_no}：【大模型提取要素结果】消息已返回')
                    break
                else:
                    callback_logger.warning(f'{task_no}：【大模型提取要素结果】消息返回失败，重试中...')
                    time.sleep(retry_delay)
        except Exception as e:
            callback_logger.error(f'{task_no}：【大模型提取要素结果】消息返回失败: {e}')
    
    def send_ocr_result(self, task_no: str, ocr_data: dict, retry_count: int = 3, retry_delay: int = 3):
        """发送OCR结果"""
        try:
            for _ in range(retry_count):
                resp = requests.post(self.ocr_result_url, json=ocr_data)
                if resp.status_code == 200:
                    callback_logger.info(f'{task_no}：【OCR文件结果】消息已返回')
                    break
                else:
                    callback_logger.warning(f'{task_no}：【OCR文件结果】消息返回失败，重试中...')
                    time.sleep(retry_delay)
        except Exception as e:
            callback_logger.error(f'{task_no}：【OCR文件结果】消息返回失败: {e}')

