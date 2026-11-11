"""A tool-calling agent loop for any OpenAI-compatible chat endpoint (Ollama by default).

The loop: send the conversation and tool list to the model; run every tool it asks for; send the results back; repeat
until the model answers in plain text or max_steps is reached. Tools are plain Python callables; a tool that raises
returns {"error": ...} to the model instead of crashing the loop. Result keys starting with "_" are kept for the
caller and never sent to the model.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from dotenv import load_dotenv

from registrar.agents.common import ToolError, plain

# Read LLM_BASE_URL / LLM_MODEL from .env before taking the defaults (registrar/db.py loads it too, but may be
# imported later). Values already set in the environment win.
load_dotenv(Path(__file__).resolve().parents[2] / ".env")
DEFAULT_BASE_URL = os.environ.get("LLM_BASE_URL", "http://127.0.0.1:11434/v1")
DEFAULT_MODEL = os.environ.get("LLM_MODEL", "qwen3-coder:30b")


def make_client(base_url: str | None = None, api_key: str | None = None):
    if os.environ.get("LLM_BACKEND", "openai") == "ollama-native":  # honors think=false; see ollama_native.py
        from registrar.agents.ollama_native import OllamaNativeClient
        return OllamaNativeClient(base_url)
    from openai import OpenAI
    return OpenAI(base_url=base_url or DEFAULT_BASE_URL, api_key=api_key or os.environ.get("LLM_API_KEY", "ollama"))


@dataclass
class ToolCall:
    name: str
    arguments: dict | str
    result: dict
    ok: bool


@dataclass
class LoopResult:
    reply: str
    calls: list[ToolCall] = field(default_factory=list)
    steps: int = 0
    stopped_early: bool = False


class ToolLoop:
    def __init__(self, client, model: str, system_prompt: str, tool_specs: list[dict],
                 dispatch: Callable[[str, dict], dict], max_steps: int = 8, temperature: float = 0.0,
                 verbose: bool = False):
        self.client, self.model = client, model
        self.tool_specs = tool_specs
        self.tool_names = {t["function"]["name"] for t in tool_specs}
        self.tool_params = {t["function"]["name"]: set(t["function"].get("parameters", {}).get("properties", {}))
                            for t in tool_specs}
        self.dispatch = dispatch
        self.max_steps, self.temperature, self.verbose = max_steps, temperature, verbose
        self.messages: list[dict] = [{"role": "system", "content": system_prompt}]

    def run(self, user_text: str) -> LoopResult:
        self.messages.append({"role": "user", "content": user_text})
        result = LoopResult(reply="")
        for step in range(1, self.max_steps + 1):
            result.steps = step
            msg = self.client.chat.completions.create(model=self.model, messages=self.messages, tools=self.tool_specs,
                                                      temperature=self.temperature).choices[0].message
            calls = [(c.id, c.function.name, c.function.arguments) for c in (msg.tool_calls or [])]
            if not calls:
                calls = self._calls_written_as_text(msg.content)
            if not calls:
                result.reply = strip_think(msg.content)
                self.messages.append({"role": "assistant", "content": msg.content or ""})
                return result
            self.messages.append({"role": "assistant", "content": "", "tool_calls": [
                {"id": cid, "type": "function", "function": {
                    "name": name, "arguments": args if isinstance(args, str) else json.dumps(args)}}
                for cid, name, args in calls]})
            for cid, name, args in calls:
                call = self._run_one(name, args)
                result.calls.append(call)
                self.messages.append({"role": "tool", "tool_call_id": cid,
                                      "content": json.dumps(model_view(call.result), default=plain)})
        result.stopped_early = True
        result.reply = "Sorry, I could not finish answering that. Please try rephrasing the question."
        self.messages.append({"role": "assistant", "content": result.reply})
        return result

    def _run_one(self, name: str, raw_args) -> ToolCall:
        try:
            args = raw_args if isinstance(raw_args, dict) else json.loads(raw_args or "{}")
            if not isinstance(args, dict):
                raise ValueError
        except ValueError:
            return self._log(ToolCall(name, raw_args, {"error": "Tool arguments were not valid JSON."}, False))
        if name not in self.tool_names:
            return self._log(ToolCall(name, args, {"error": f"There is no tool named {name!r}."}, False))
        # Small models often add arguments a tool does not declare (e.g. a course to a no-argument tool). Drop them;
        # a call that still lacks a required argument fails below as before.
        ignored = sorted(set(args) - self.tool_params.get(name, set()))
        args = {k: v for k, v in args.items() if k not in ignored}
        try:
            result = self.dispatch(name, args)
            if ignored and isinstance(result, dict):
                result = {**result, "ignored_arguments": ignored}
            return self._log(ToolCall(name, args, result, True))
        except ToolError as e:
            return self._log(ToolCall(name, args, {"error": str(e)}, False))
        except TypeError as e:                       # wrong or missing argument names
            return self._log(ToolCall(name, args, {"error": f"Bad arguments: {e}"}, False))

    def _log(self, call: ToolCall) -> ToolCall:
        if self.verbose:
            print(f"  [tool] {call.name}({json.dumps(call.arguments, default=str)}) -> "
                  f"{json.dumps(model_view(call.result), default=plain)[:300]}")
        return call

    def _calls_written_as_text(self, content: str | None) -> list[tuple]:
        """Some local models print a tool call as JSON instead of using the tool-call channel. Accept it only when
        the whole reply is a JSON object naming a known tool."""
        text = strip_think(content)
        text = re.sub(r"^```(?:json)?|```$", "", re.sub(r"</?tool_call>", "", text).strip()).strip()
        if not text.startswith("{"):
            return []
        try:
            obj = json.loads(text)
        except ValueError:
            return []
        if not isinstance(obj, dict) or obj.get("name") not in self.tool_names:
            return []
        args = obj.get("arguments", obj.get("parameters", {}))
        return [(f"call_{uuid.uuid4().hex[:8]}", obj["name"], args)]


def model_view(result: dict) -> dict:
    """What the model sees of a tool result: keys starting with "_" stay on the Python side."""
    return {k: v for k, v in result.items() if not k.startswith("_")}


def strip_think(text: str | None) -> str:
    return re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL).strip()
