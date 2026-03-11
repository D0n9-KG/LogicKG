import os
import re

from dotenv import load_dotenv
from openai import AzureOpenAI, OpenAI

from .logger import logger

load_dotenv()


class LLMCompletionCall:
    def __init__(self):
        self.llm_model = os.getenv("LLM_MODEL", "deepseek-chat")
        self.llm_base_url = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
        self.llm_api_key = os.getenv("LLM_API_KEY", "")
        self.openai_provider = os.getenv("OPENAI_PROVIDER", "openai").lower()
        self.client = None

        if not self.llm_api_key:
            return

        if self.openai_provider == "azure":
            self.api_version = os.getenv("API_VERSION", "2025-01-01-preview")
            self.client = AzureOpenAI(
                azure_endpoint=self.llm_base_url,
                api_key=self.llm_api_key,
                api_version=self.api_version,
            )
        else:
            self.client = OpenAI(base_url=self.llm_base_url, api_key=self.llm_api_key)

    def call_api(self, content: str) -> str:
        if self.client is None:
            raise RuntimeError("LLM client is not configured for vendored TreeComm naming helpers")

        try:
            completion = self.client.chat.completions.create(
                model=self.llm_model,
                messages=[{"role": "user", "content": content}],
                temperature=0.3,
            )
            raw = completion.choices[0].message.content or ""
            return self._clean_llm_content(raw)
        except Exception as exc:  # noqa: BLE001
            logger.error(f"LLM api calling failed. Error: {exc}")
            raise

    def _clean_llm_content(self, text: str) -> str:
        if not isinstance(text, str):
            return ""
        cleaned = text.replace("\r\n", "\n").replace("\r", "\n").strip()
        cleaned = re.sub(r"[\u200B-\u200D\uFEFF]", "", cleaned)
        if cleaned.startswith("```") and cleaned.endswith("```") and len(cleaned) >= 6:
            cleaned = cleaned[3:-3].strip()
        if cleaned.lower().startswith("json\n"):
            cleaned = cleaned.split("\n", 1)[1].strip()
        return cleaned
