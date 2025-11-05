# module/llm_openai.py
import json
import re
import requests

class OpenAICompatClient:
    """
    直连 vLLM/OpenAI 兼容接口（/v1/chat/completions）
    """
    def __init__(
        self,
        base_url: str,
        model: str,
        timeout: int = 60,
        system: str = "",
        temperature: float = 0.2,
        top_p: float = 0.95,
        max_tokens: int = 1024,
        api_key: str | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.system = system or ""
        self.temperature = temperature
        self.top_p = top_p
        self.max_tokens = max_tokens
        self.api_key = api_key

    def _headers(self):
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def generate(self, prompt: str) -> str:
        """
        返回大模型的纯文本回答（chat.completions）
        """
        payload = {
            "model": self.model,
            "messages": (
                [{"role": "system", "content": self.system}] if self.system else []
            ) + [{"role": "user", "content": prompt}],
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_tokens,
        }
        url = f"{self.base_url}/v1/chat/completions"
        resp = requests.post(url, headers=self._headers(), json=payload, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    @staticmethod
    def format_LLM_result(text: str) -> str:
        """
        兼容你现有流程：抽出 JSON（去掉```json fenced code等）
        """
        if not isinstance(text, str):
            raise ValueError("LLM 返回内容不是字符串")

        # 去除 Markdown 代码块
        text = text.strip()
        code_fence = re.search(r"```(?:json)?\s*(.+?)\s*```", text, flags=re.S)
        if code_fence:
            text = code_fence.group(1).strip()

        # 尝试定位第一个 { 和最后一个 } 之间的内容
        l, r = text.find("{"), text.rfind("}")
        if l != -1 and r != -1 and r > l:
            text = text[l : r + 1].strip()

        # 校验是否为 JSON
        try:
            _ = json.loads(text)
        except Exception:
            # 尝试常见错误修复：去掉末尾逗号
            text = re.sub(r",\s*}", "}", text)
            text = re.sub(r",\s*]", "]", text)
            _ = json.loads(text)  # 再试一次，失败就抛
        return text
