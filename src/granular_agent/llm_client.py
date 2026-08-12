"""LLM client: wraps DeepSeek + Paratera APIs for extraction and embedding."""

from __future__ import annotations

import json
import os
import re
import ssl
import urllib.request
from typing import Any

_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE


def load_env(path: str = "C:/Users/D0n9/Desktop/LogicKG/.env") -> dict:
    env = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


ENV = load_env()


def call_llm(prompt: str, model: str = "deepseek-chat", max_tokens: int = 4000,
             temperature: float = 0.0) -> str | None:
    """Call DeepSeek chat API."""
    key = ENV.get("DEEPSEEK_API_KEY")
    if not key:
        raise RuntimeError("no DEEPSEEK_API_KEY")
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }).encode()
    req = urllib.request.Request(
        "https://api.deepseek.com/v1/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    for attempt in range(3):
        try:
            raw = urllib.request.urlopen(req, context=_CTX, timeout=180).read()
            return json.loads(raw)["choices"][0]["message"]["content"]
        except Exception:
            if attempt == 2:
                return None
    return None


def call_paratera(prompt: str, model: str = "Kimi-K2.6", max_tokens: int = 4000,
                  temperature: float = 0.0) -> str | None:
    """Call Paratera API (Kimi/GLM/Qwen)."""
    key = ENV.get("PARATERA_API_KEY")
    base = ENV.get("PARATERA_BASE_URL", "").rstrip("/")
    if not key:
        return None
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }).encode()
    req = urllib.request.Request(
        base + "/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    for attempt in range(3):
        try:
            raw = urllib.request.urlopen(req, context=_CTX, timeout=180).read()
            return json.loads(raw)["choices"][0]["message"]["content"]
        except Exception:
            if attempt == 2:
                return None
    return None


def embed_batch(texts: list[str], model: str = "GLM-Embedding-2") -> list[list[float]]:
    """Call Paratera embedding API."""
    key = ENV.get("PARATERA_API_KEY")
    base = ENV.get("PARATERA_BASE_URL", "").rstrip("/")
    if not key or not texts:
        return []
    out = []
    batch_size = 32
    for i in range(0, len(texts), batch_size):
        chunk = texts[i:i + batch_size]
        body = json.dumps({"model": model, "input": chunk}).encode()
        req = urllib.request.Request(
            base + "/embeddings",
            data=body,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        )
        raw = urllib.request.urlopen(req, context=_CTX, timeout=60).read()
        data = json.loads(raw).get("data", [])
        data.sort(key=lambda x: x.get("index", 0))
        out.extend([d["embedding"] for d in data])
    return out


def cosine_sim(a: list[float], b: list[float]) -> float:
    import math
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def parse_json_response(text: str | None) -> Any:
    """Parse JSON from LLM response, handling markdown fences and extra text."""
    if not text:
        return None
    text = re.sub(r"```json|```", "", text, flags=re.S)
    m = re.search(r"(\[.*\]|\{.*\})", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None
