"""AI extraction provider abstraction.

Supported providers:
    - openai             (api.openai.com, needs OPENAI_API_KEY)
    - openai-compatible  (any OpenAI-compatible endpoint via OPENAI_BASE_URL)
    - ollama             (local, via OLLAMA_BASE_URL)
    - none               (rule-based extraction only; no AI calls)

All providers implement ``extract_structured`` which returns a validated
DocumentExtraction (Pydantic) or raises AIProviderError. Responses are cached
by content hash in the processing DB.
"""
from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod


from app.ai.prompts import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE
from app.ai.schemas import DocumentExtraction
from app.core.config import AIConfig
from app.core.exceptions import AIProviderError
from app.core.logging import get_logger

logger = get_logger(__name__)


class AIExtractor(ABC):
    """Interface so the AI provider can be swapped without touching the pipeline."""

    provider_name: str = "abstract"

    @abstractmethod
    def extract_structured(
        self,
        content: str,
        filename: str,
        company: str,
        year_hint: int | None,
        unit_hint: str,
        page_first: int,
        page_last: int,
    ) -> DocumentExtraction:
        ...

    # -- shared helpers ---------------------------------------------------
    def build_messages(self, content: str, filename: str, company: str,
                       year_hint: int | None, unit_hint: str,
                       page_first: int, page_last: int) -> list[dict[str, str]]:
        user = USER_PROMPT_TEMPLATE.format(
            filename=filename,
            company=company,
            year_hint=year_hint if year_hint else "unknown",
            unit_hint=unit_hint if unit_hint else "unknown",
            page_first=page_first,
            page_last=page_last,
            content=content[:60_000],  # hard cap to control cost
        )
        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ]

    def parse_response(self, raw: str) -> DocumentExtraction:
        """Parse + validate model output; tolerant of markdown fences."""
        text = raw.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:]
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1:
            raise AIProviderError("AI response contained no JSON object")
        try:
            data = json.loads(text[start : end + 1])
            return DocumentExtraction.model_validate(data)
        except json.JSONDecodeError as exc:
            raise AIProviderError(f"Invalid JSON from AI: {exc}") from exc
        except Exception as exc:
            raise AIProviderError(f"AI response failed schema validation: {exc}") from exc


class OpenAICompatibleExtractor(AIExtractor):
    """Works with OpenAI and any OpenAI-compatible API (incl. Ollama's /v1)."""

    def __init__(self, cfg: AIConfig, base_url: str | None = None):
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise AIProviderError("The 'openai' package is required for AI extraction") from exc
        self.cfg = cfg
        self.provider_name = "openai" if base_url is None else "openai-compatible"
        self.client = OpenAI(api_key=cfg.api_key, base_url=base_url)

    def extract_structured(self, content, filename, company, year_hint, unit_hint,
                           page_first, page_last) -> DocumentExtraction:
        messages = self.build_messages(content, filename, company, year_hint,
                                       unit_hint, page_first, page_last)
        try:
            resp = self.client.chat.completions.create(
                model=self.cfg.model,
                messages=messages,
                temperature=self.cfg.temperature,
                max_tokens=self.cfg.max_tokens,
                response_format={"type": "json_object"},
            )
            raw = resp.choices[0].message.content or ""
        except Exception as exc:
            raise AIProviderError(f"AI API call failed: {exc}") from exc
        return self.parse_response(raw)


class OllamaExtractor(AIExtractor):
    """Local Ollama models via the native /api/chat endpoint (no API key)."""

    provider_name = "ollama"

    def __init__(self, cfg: AIConfig, base_url: str | None = None):
        self.cfg = cfg
        self.base_url = (base_url or "http://localhost:11434").rstrip("/")

    def extract_structured(self, content, filename, company, year_hint, unit_hint,
                           page_first, page_last) -> DocumentExtraction:
        import urllib.request

        messages = self.build_messages(content, filename, company, year_hint,
                                       unit_hint, page_first, page_last)
        payload = json.dumps(
            {
                "model": self.cfg.model,
                "messages": messages,
                "stream": False,
                "format": "json",
                "options": {"temperature": self.cfg.temperature},
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            raise AIProviderError(f"Ollama request failed: {exc}") from exc
        raw = body.get("message", {}).get("content", "")
        return self.parse_response(raw)


class NullExtractor(AIExtractor):
    """No AI. The pipeline falls back to rule-based extraction only."""

    provider_name = "none"

    def extract_structured(self, *args, **kwargs) -> DocumentExtraction:
        raise AIProviderError("AI provider is disabled (AI_PROVIDER=none)")


def create_extractor(cfg: AIConfig) -> AIExtractor:
    """Factory: build the configured provider."""
    provider = cfg.provider.lower()
    if provider == "none":
        return NullExtractor()
    if provider == "openai":
        if not cfg.api_key:
            raise AIProviderError("OPENAI_API_KEY is not set")
        return OpenAICompatibleExtractor(cfg)
    if provider == "openai-compatible":
        if not cfg.base_url:
            raise AIProviderError("OPENAI_BASE_URL is not set for openai-compatible provider")
        return OpenAICompatibleExtractor(cfg, base_url=cfg.base_url)
    if provider == "ollama":
        return OllamaExtractor(cfg, base_url=cfg.base_url)
    raise AIProviderError(f"Unknown AI provider: {cfg.provider}")


def cache_key_for(content: str, model: str, company: str, filename: str) -> str:
    h = hashlib.sha256()
    h.update(model.encode())
    h.update(company.encode())
    h.update(filename.encode())
    h.update(content.encode()[:100_000])
    return h.hexdigest()
