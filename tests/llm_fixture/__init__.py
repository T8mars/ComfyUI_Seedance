"""Explicit isolated-server acceptance; all chat/model HTTP is local recorded data."""

import json
import os
from pathlib import Path
import sys
import uuid


def install():
    path = os.getenv("SEEDANCE_LLM_FIXTURE_STATE")
    if not path:
        return {}
    from aiohttp import web
    import execution
    import nodes as comfy_nodes
    from server import PromptServer

    state = json.loads(Path(path).read_text(encoding="utf-8"))
    counts = {"post": 0, "get": 0}
    failures = set()

    @PromptServer.instance.routes.post("/seedance_llm_fixture/validate")
    async def validate(request):
        body = await request.json()
        result = await execution.validate_prompt(str(uuid.uuid4()), body["prompt"], None)
        return web.json_response({"valid": result[0], "error": result[1], "node_errors": result[3]})

    @PromptServer.instance.routes.post("/seedance_llm_fixture/reuse")
    async def reuse(request):
        plugin = sys.modules[comfy_nodes.NODE_CLASS_MAPPINGS["Seedance_LLM_API"].__module__]
        module = plugin.llm
        class Response:
            status_code = 200
            headers = {"Content-Type": "text/event-stream"}
            def __init__(self, value):
                self.value = value
            def json(self):
                return self.value
            def iter_lines(self, **kwargs):
                for text in (self.value["choices"][0]["message"]["content"],):
                    yield "data: "+json.dumps({"choices":[{"index":0,"delta":{"content":text}}]})
                    yield ""
                yield 'data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}'
                yield ""
                yield "data: [DONE]"
                yield ""
            def close(self):
                pass
        class Session:
            def get(self, url, **kwargs):
                if url != module.BASE_URL+"/v1/models":
                    raise RuntimeError("Fixture blocks unknown GET")
                counts["get"] += 1
                return Response({"data":[{"id":model} for model in module.MODELS[:2]]+[{"id":"minimax-h3-image","supported_endpoint_types":["openai"]}]})
            def post(self, url, json=None, **kwargs):
                if url != module.BASE_URL+"/v1/chat/completions" or json.get("model") not in module.MODELS:
                    raise RuntimeError("Fixture blocks unknown POST")
                counts["post"] += 1
                if failures:
                    failures.clear()
                    raise RuntimeError("Injected local chat failure")
                case = "vision_stream_history" if any(isinstance(item.get("content"),list) for item in json["messages"]) else "text"
                result = state[case]["result"]
                return Response({"model":json["model"],"choices":[{"message":{"role":"assistant","content":result[0],"reasoning_content":result[1]}}]})
        module._session = lambda: Session()
        module._catalog_cache.clear()
        return web.json_response({"ready": True})

    @PromptServer.instance.routes.get("/seedance_llm_fixture/counts")
    async def counters(request):
        return web.json_response(dict(counts))

    @PromptServer.instance.routes.post("/seedance_llm_fixture/fail-next")
    async def fail_next(request):
        failures.add("next")
        return web.json_response({"ready": True})
    return {}


NODE_CLASS_MAPPINGS = install()
