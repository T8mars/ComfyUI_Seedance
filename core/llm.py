"""Seedance-only chat completion and positively identified LLM catalog."""

import base64
import hashlib
import json
import math
import re
import threading
import time
from urllib.parse import urlsplit

import torch

from .client import SeedanceAPIError, _headers, _session
from .media import image_to_png_bytes
from .runtime import check_cancelled


BASE_URL = "https://api.seedance.nz"
# Catalog endpoint tags also include media models. Only documented chat IDs qualify.
MODELS = [
    "qwen/qwen3.8-flash-next", "qwen/qwen3.8-max", "qwen/qwen3.8-omni-flash",
    "deepseek/deepseek-v4.1-flash", "deepseek/deepseek-v4-flash-vision-exp",
    "glm/glm-5.3-flash", "glm-5.3", "kimi-k3", "zhenzhen/gk-4.6",
    "zhenzhen/g6-astra", "zhenzhen/g6-sol", "zhenzhen/g6-luna",
    "zhenzhen/g5.6-sol", "zhenzhen/g5.6-terra", "zhenzhen/g5.6-luna",
    "zhenzhen/g5.5", "zhenzhen/gm-3.8-flash", "zhenzhen/gm-4-argon", "zhenzhen-op-5.5", "zhenzhen-fb-5.2",
    "zhenzhen/g6.1-sol", "zhenzhen/g6.2-astra", "zhenzhen/g6.2-sol",
    "zhenzhen/gm-4-hydrogen", "zhenzhen/gm-4-carbon", "zhenzhen/gm-4-neon", "zhenzhen/hy-4-flash",
    "moonshotai/kimi-k3.1-pro", "zhenzhen/gk-4.7",
]
_catalog_cache = {}
_catalog_lock = threading.Lock()


def check_origin(config):
    parsed = urlsplit(str(config.get("base_url", "")))
    if (parsed.scheme != "https" or parsed.hostname != "api.seedance.nz"
            or parsed.port not in (None, 443) or parsed.username or parsed.password
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        raise SeedanceAPIError("Seedance LLM only accepts https://api.seedance.nz | LLM 仅支持平价小屋渠道")
    if not config.get("api_key"):
        raise SeedanceAPIError("Seedance API key is required")


def safe_error(error, config=None):
    text = str(error)
    key = (config or {}).get("api_key")
    if key:
        text = text.replace(key, "[REDACTED]")
    return re.sub(r"sk-[A-Za-z0-9_-]+|data:image/[^\s\"']+", "[REDACTED]", text)[:700]


def catalog(config, force=False):
    check_origin(config)
    identity = hashlib.sha256(config["api_key"].encode()).digest()
    with _catalog_lock:
        cached = _catalog_cache.get(identity)
        if not force and cached and time.monotonic() - cached[0] < 120:
            return list(cached[1])
    response = _session().get(BASE_URL+"/v1/models", headers=_headers(config["api_key"], with_json=False),
                              timeout=(8, 30), allow_redirects=False)
    try:
        if response.status_code != 200:
            raise SeedanceAPIError(f"LLM model catalog returned HTTP {response.status_code}")
        body = response.json()
        rows = body.get("data") if isinstance(body, dict) else None
        if not isinstance(rows, list):
            raise SeedanceAPIError("Invalid LLM model catalog response")
        ids = {row.get("id") for row in rows if isinstance(row, dict) and isinstance(row.get("id"), str)}
        result = [model for model in MODELS if model in ids]
        if not result:
            raise SeedanceAPIError("No documented chat models are available for this API key")
        with _catalog_lock:
            if len(_catalog_cache) >= 32:
                _catalog_cache.clear()
            _catalog_cache[identity] = (time.monotonic(), tuple(result))
        return result
    finally:
        response.close()


def _content(value):
    if isinstance(value, str):
        return
    if not isinstance(value, list):
        raise SeedanceAPIError("History content must be text or text/image blocks")
    for part in value:
        if not isinstance(part, dict):
            raise SeedanceAPIError("Invalid history content block")
        if part.get("type") == "text" and isinstance(part.get("text"), str):
            continue
        if part.get("type") == "image_url" and isinstance(part.get("image_url"), dict):
            url = part["image_url"].get("url", "")
            if isinstance(url, str) and (url.startswith("data:image/") or urlsplit(url).scheme in ("http", "https")):
                continue
        raise SeedanceAPIError("Only text and image_url history blocks are supported")


def history(value):
    if not isinstance(value, str):
        raise SeedanceAPIError("history must be a JSON text array")
    try:
        messages = json.loads(value) if value.strip() else []
    except ValueError as error:
        raise SeedanceAPIError("Invalid history JSON") from error
    if not isinstance(messages, list):
        raise SeedanceAPIError("History must be a messages array")
    for message in messages:
        if not isinstance(message, dict) or message.get("role") not in ("system", "user", "assistant"):
            raise SeedanceAPIError("History roles must be system, user or assistant")
        if set(message) - {"role", "content"}:
            raise SeedanceAPIError("History contains unsupported message fields")
        _content(message.get("content"))
    return messages


def validate(kwargs, strict=False):
    if kwargs.get("model") is not None and kwargs["model"] not in MODELS:
        raise SeedanceAPIError("Select a documented Seedance chat model")
    for name in ("prompt", "system_prompt", "history"):
        value = kwargs.get(name)
        if value is not None and not isinstance(value, str):
            raise SeedanceAPIError(name + " must be text")
    if strict and not kwargs.get("prompt", "").strip():
        raise SeedanceAPIError("A non-empty prompt is required | 必须填写提示词")
    if kwargs.get("history") is not None:
        history(kwargs["history"])
    for name, low, high in (("max_tokens", 1, 32768), ("timeout", 10, 600)):
        value = kwargs.get(name)
        if value is not None and (not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high):
            raise SeedanceAPIError(f"{name} must be an integer from {low} to {high}")
    if kwargs.get("temperature_mode", "api_default") not in ("api_default", "custom"):
        raise SeedanceAPIError("Invalid temperature mode")
    if kwargs.get("temperature_mode") == "custom":
        value = kwargs.get("temperature", .6)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or not 0 <= value <= 2:
            raise SeedanceAPIError("temperature must be between 0 and 2")
    if kwargs.get("stream") is not None and not isinstance(kwargs["stream"], bool):
        raise SeedanceAPIError("stream must be a boolean")
    for key, value in kwargs.items():
        if re.fullmatch(r"image\d+", key) and value is not None and key not in ("image1", "image2", "image3", "image4"):
            raise SeedanceAPIError("This node exposes four local image inputs")
    return True


def payload(kwargs):
    validate(kwargs, strict=True)
    messages = history(kwargs.get("history", ""))
    system = kwargs.get("system_prompt", "You are a helpful assistant.").strip()
    if system:
        messages = [message for message in messages if message["role"] != "system"]
        messages.insert(0, {"role": "system", "content": system})
    parts = [{"type": "text", "text": kwargs["prompt"].strip()}]
    for index in range(1, 5):
        image = kwargs.get(f"image{index}")
        if image is None:
            continue
        if kwargs.get("model") == "glm-5.3":
            raise SeedanceAPIError("glm-5.3 is text-only | 该模型仅支持文本")
        shape = getattr(image, "shape", ())
        if len(shape) != 4 or shape[0] != 1 or shape[-1] not in (3, 4) or min(shape[1:3]) < 1 or not torch.isfinite(image).all():
            raise SeedanceAPIError("Each reference requires one finite RGB/RGBA IMAGE")
        data = base64.b64encode(image_to_png_bytes(image)).decode("ascii")
        parts.append({"type": "image_url", "image_url": {"url": "data:image/png;base64,"+data}})
    if kwargs.get("model") == "glm-5.3" and any(isinstance(message["content"], list) and any(p["type"] == "image_url" for p in message["content"]) for message in messages):
        raise SeedanceAPIError("glm-5.3 history must contain text only")
    messages.append({"role": "user", "content": parts if len(parts) > 1 else parts[0]["text"]})
    body = {"model": kwargs.get("model", MODELS[0]), "messages": messages,
            "max_tokens": kwargs.get("max_tokens", 1024), "stream": kwargs.get("stream", False)}
    if kwargs.get("temperature_mode") == "custom":
        body["temperature"] = kwargs.get("temperature", .6)
    if len(json.dumps(body).encode()) > 32 * 1024 * 1024:
        raise SeedanceAPIError("Chat request exceeds the local 32 MiB memory guard")
    return body


def text_content(value):
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    if isinstance(value, list):
        return "".join(part.get("text", "") for part in value if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str))
    raise SeedanceAPIError("Unexpected chat text response")


def read_stream(response, on_progress=None):
    text, reasoning, pending = [], [], []
    size, finished, done = 0, False, False
    def event():
        nonlocal finished, done
        data = "\n".join(pending)
        pending.clear()
        if data == "[DONE]":
            done = True
            return
        try:
            item = json.loads(data)
        except ValueError as error:
            raise SeedanceAPIError("Invalid JSON in chat stream; request was not replayed") from error
        if not isinstance(item, dict) or item.get("error"):
            raise SeedanceAPIError("Chat stream returned an error")
        for choice in item.get("choices", []):
            if choice.get("index", 0) != 0:
                continue
            delta = choice.get("delta", {})
            text.append(text_content(delta.get("content")))
            reasoning.append(text_content(delta.get("reasoning_content") or delta.get("reasoning")))
            finished = finished or choice.get("finish_reason") is not None
        if on_progress:
            on_progress(min(90, 25+len(text)))
    response.encoding = "utf-8"
    for line in response.iter_lines(decode_unicode=True):
        check_cancelled()
        size += len(line.encode("utf-8")) if isinstance(line, str) else len(line)
        if size > 8 * 1024 * 1024:
            raise SeedanceAPIError("Chat response exceeds the local 8 MiB memory guard")
        if not line:
            if pending:
                event()
                if done:
                    break
        elif line.startswith("data:"):
            pending.append(line[5:].lstrip())
    if pending:
        event()
    if not (finished or done):
        raise SeedanceAPIError("Chat stream ended before completion; request was not replayed")
    return "".join(text), "".join(reasoning)


def complete(config, kwargs, on_progress=None):
    check_origin(config)
    body = payload(kwargs)
    check_cancelled()
    response = _session().post(BASE_URL+"/v1/chat/completions", headers=_headers(config["api_key"]), json=body,
                               timeout=(8, kwargs.get("timeout", 180)), stream=body["stream"], allow_redirects=False)
    try:
        if response.status_code != 200:
            raise SeedanceAPIError(f"LLM returned HTTP {response.status_code}; request was not replayed")
        if body["stream"]:
            if "text/event-stream" not in response.headers.get("Content-Type", "").lower():
                raise SeedanceAPIError("Expected a text/event-stream response")
            text, reasoning = read_stream(response, on_progress)
            result = {"model": body["model"], "choices": [{"message": {"role": "assistant", "content": text, "reasoning_content": reasoning}}]}
        else:
            result = response.json()
            if not isinstance(result, dict) or not isinstance(result.get("choices"), list) or not result["choices"]:
                raise SeedanceAPIError("LLM response has no choices")
            message = result["choices"][0].get("message", {})
            text = text_content(message.get("content"))
            reasoning = text_content(message.get("reasoning_content") or message.get("reasoning"))
            result = {key: result[key] for key in ("id", "object", "created", "model", "choices") if key in result}
        check_cancelled()
        if not text.strip():
            raise SeedanceAPIError("No final answer returned; increase max_tokens if reasoning exhausted the output budget")
        messages = body["messages"] + [{"role": "assistant", "content": text}]
        return text, reasoning, json.dumps(messages, ensure_ascii=False), json.dumps(result, ensure_ascii=False)
    finally:
        response.close()
