import ollama
import httpx
import re
import time
from loguru import logger


class OllamaClient():
    def __init__(self, host, port, timeout=120, **kwargs):
        self.client = ollama.Client(host=f'http://{host}:{port}', timeout=timeout)
        self.initial_paras = kwargs

        log_name = 'LLM'
        logger.add(f"logs/module_{log_name}_{{time:YYYY-MM-DD}}.log",
               level="INFO",
               rotation="00:00",
               filter=lambda record: record["extra"].get("name") == log_name,
               enqueue=False,
               buffering=1)
        self.logger = logger.bind(name=log_name)

    @staticmethod
    def first_value(*args):
        for x in args:
            if x is not None:
                return x
        return

    def generate(self, prompt, retry_count=3, retry_delay=3, **kwargs):
        # 初始化 options 字典
        options = {}
        for para in ['temperature', 'top_k', 'top_p']:
            options[para] = self.first_value(kwargs.get(para), self.initial_paras.get(para), 0)

        #options['num_ctx'] = self.first_value(kwargs.get('num_ctx'), self.initial_paras.get('num_ctx'), 2048)

        # 获取其他参数
        model = self.first_value(kwargs.get('model'), self.initial_paras.get('model'))
        system = self.first_value(kwargs.get('system'), self.initial_paras.get('system'))
        _format = self.first_value(kwargs.get('format'), self.initial_paras.get('format'))
        keep_alive = self.first_value(kwargs.get('keep_alive'), self.initial_paras.get('keep_alive'))

        # 尝试重试逻辑
        for attempt in range(retry_count):
            try:
                # 调用模型生成
                response = self.client.generate(
                    model=model,
                    prompt=prompt,
                    format=_format,
                    keep_alive=keep_alive,
                    options=options,
                    system=system
                )
                return response['response']  # 返回生成的响应
            except httpx.ReadTimeout:
                # 如果是超时错误，打印警告并等待重试
                self.logger.warning(f'调用大模型返回结果超时，尝试第 {attempt + 1} 次重试')
            except Exception as e:
                # 其他异常时，记录错误并继续尝试
                self.logger.error('大模型生成结果失败')
                self.logger.exception(e)

            # 如果失败，等待一段时间后再重试
            if attempt < retry_count - 1:
                time.sleep(retry_delay)  # 延迟一段时间再重试

        # 所有尝试都失败时返回空字符串
        return ''

    @ staticmethod
    def format_LLM_result(result):
        result = re.sub('^```json\n','',result)
        result = result.strip('`\n')
        result = result.replace('.%','%')
        return result
