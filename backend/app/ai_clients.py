from __future__ import annotations

import hashlib
import json
import math
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AIClientConfig:
    base_url: str | None
    api_key: str | None
    embedding_provider: str
    embedding_model: str
    embedding_dimensions: int
    llm_provider: str
    llm_model: str
    timeout_seconds: float
    llm_base_url: str | None = None
    llm_api_key: str | None = None


class EmbeddingClient:
    def __init__(self, config: AIClientConfig) -> None:
        self.config = config
        self.last_provider = "hash"
        self.last_error: str | None = None

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if self._should_call_remote():
            try:
                vectors = self._remote_embeddings(texts)
                if vectors:
                    self.last_provider = "openai_compatible"
                    self.last_error = None
                    return [_normalize(vector) for vector in vectors]
            except Exception as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
        self.last_provider = "hash"
        return [hash_embedding(text, self.config.embedding_dimensions) for text in texts]

    def _should_call_remote(self) -> bool:
        return (
            self.config.embedding_provider in {"auto", "qwen", "openai_compatible"}
            and bool(self.config.base_url)
            and bool(self.config.api_key)
        )

    def _remote_embeddings(self, texts: list[str]) -> list[list[float]]:
        url = f"{self.config.base_url.rstrip('/')}/embeddings"
        payload = json.dumps(
            {
                "model": self.config.embedding_model,
                "input": texts,
                "dimensions": self.config.embedding_dimensions,
                "encoding_format": "float",
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
            body = json.loads(response.read().decode("utf-8"))
        data = body.get("data", [])
        data.sort(key=lambda item: item.get("index", 0))
        vectors = [item["embedding"] for item in data if item.get("embedding")]
        if len(vectors) != len(texts):
            raise ValueError("embedding response count mismatch")
        return vectors


class LLMClient:
    def __init__(self, config: AIClientConfig) -> None:
        self.config = config
        self.last_provider = "disabled"
        self.last_error: str | None = None

    def summarize_agent(self, *, agent_name: str, verdict: str, reasons: list[str], evidence_snippets: list[str]) -> dict[str, Any]:
        if self._should_call_remote():
            try:
                content = self._remote_chat(agent_name, verdict, reasons, evidence_snippets)
                self.last_provider = "openai_compatible"
                self.last_error = None
                return {"llm_used": True, "llm_reasoning": content, "llm_error": None}
            except (urllib.error.URLError, TimeoutError, ValueError, KeyError, json.JSONDecodeError) as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
        self.last_provider = "disabled"
        return {
            "llm_used": False,
            "llm_reasoning": "LLM 未启用或调用失败，本节点使用规则与检索证据生成确定性解释。",
            "llm_error": self.last_error,
        }

    def _should_call_remote(self) -> bool:
        base = self.config.llm_base_url or self.config.base_url
        key = self.config.llm_api_key or self.config.api_key
        return (
            self.config.llm_provider in {"auto", "qwen", "openai_compatible"}
            and bool(base)
            and bool(key)
        )

    def _remote_chat(self, agent_name: str, verdict: str, reasons: list[str], evidence_snippets: list[str]) -> str:
        base = self.config.llm_base_url or self.config.base_url
        key = self.config.llm_api_key or self.config.api_key
        url = f"{base.rstrip('/')}/chat/completions"
        prompt = (
            "你是化工合规预审系统中的专业子 Agent。"
            "请只基于给定规则结论和证据片段，用两句话解释判断依据；"
            "不得改变 verdict，不得输出最终法律意见。\n"
            "/no_think\n"
            f"Agent: {agent_name}\n"
            f"Verdict: {verdict}\n"
            f"Reasons: {'；'.join(reasons)}\n"
            f"Evidence: {' | '.join(evidence_snippets[:4])}"
        )
        payload = json.dumps(
            {
                "model": self.config.llm_model,
                "messages": [
                    {"role": "system", "content": "你只做证据归纳和解释，不做最终放行决定。"},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.2,
                "max_tokens": 220,
                "enable_thinking": False,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
            body = json.loads(response.read().decode("utf-8"))
        return body["choices"][0]["message"]["content"].strip()


def hash_embedding(text: str, dimensions: int = 1024) -> list[float]:
    vector = [0.0] * dimensions
    tokens = text.lower().split()
    if not tokens:
        tokens = [text.lower()]
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        for offset in range(0, min(len(digest), 16), 2):
            index = int.from_bytes(digest[offset : offset + 2], "big") % dimensions
            sign = 1.0 if digest[offset] % 2 == 0 else -1.0
            vector[index] += sign
    return _normalize(vector)


def cosine(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    length = min(len(left), len(right))
    dot = sum(left[index] * right[index] for index in range(length))
    left_norm = math.sqrt(sum(value * value for value in left[:length]))
    right_norm = math.sqrt(sum(value * value for value in right[:length]))
    return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if not norm:
        return vector
    return [value / norm for value in vector]
