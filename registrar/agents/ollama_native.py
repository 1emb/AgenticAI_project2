"""A drop-in client for ToolLoop that talks to Ollama's native /api/chat instead of the OpenAI-compatible endpoint.

Why: the OpenAI-compatible endpoint ignores Ollama's `think` switch, so reasoning models (qwen3) think before every
tool call; on a CPU that is minutes per step. The native API honors `think: false`. Use it with
LLM_BACKEND=ollama-native (see registrar/agents/loop.make_client). The object returned by
client.chat.completions.create(...) has the attributes ToolLoop reads: .choices[0].message.content and
.choices[0].message.tool_calls[i].id / .function.name / .function.arguments (a JSON string).
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
import uuid
from types import SimpleNamespace as NS


class _Completions:
    def __init__(self, base: str, think: bool, timeout: float, options: dict):
        self.base, self.think, self.timeout, self.options = base, think, timeout, options

    def create(self, model: str, messages: list[dict], tools: list[dict] | None = None, temperature: float = 0.0,
               **_ignored):
        body = {"model": model, "messages": [self._to_native(m) for m in messages], "stream": False,
                "think": self.think, "options": {"temperature": temperature, **self.options}}
        if tools:
            body["tools"] = tools
        data = json.dumps(body).encode()
        for attempt in range(3):  # Ollama restarts a crashed model runner (e.g. killed when memory runs out)
            try:
                req = urllib.request.Request(self.base + "/api/chat", data, {"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    msg = json.load(r)["message"]
                break
            except urllib.error.HTTPError as e:
                if e.code < 500 or attempt == 2:
                    raise
                time.sleep(3 * (attempt + 1))
        calls = [NS(id=f"call_{uuid.uuid4().hex[:8]}", type="function",
                    function=NS(name=c["function"]["name"], arguments=json.dumps(c["function"].get("arguments", {}))))
                 for c in msg.get("tool_calls") or []]
        return NS(choices=[NS(message=NS(content=msg.get("content") or "", tool_calls=calls or None))])

    @staticmethod
    def _to_native(m: dict) -> dict:
        out = {"role": m["role"], "content": m.get("content") or ""}
        if m.get("tool_calls"):
            out["tool_calls"] = [{"function": {"name": c["function"]["name"],
                                               "arguments": json.loads(c["function"]["arguments"] or "{}")}}
                                 for c in m["tool_calls"]]
        return out


class OllamaNativeClient:
    def __init__(self, base_url: str | None = None, think: bool | None = None, timeout: float = 600.0):
        base = (base_url or os.environ.get("LLM_BASE_URL", "http://127.0.0.1:11434/v1")).rstrip("/")
        base = base[:-3] if base.endswith("/v1") else base
        think = (os.environ.get("LLM_THINK", "false").lower() == "true") if think is None else think
        options = {"num_ctx": int(os.environ.get("LLM_NUM_CTX", "8192"))}
        self.chat = NS(completions=_Completions(base, think, timeout, options))
