"""Isolated native acceptance: only reuse recorded responses, never create tasks."""

import json
import os
from pathlib import Path
import sys
import threading
import uuid


def install():
    path = os.environ.get("H3_TURBO_RESUME_PATH")
    if not path:
        return {}
    from aiohttp import web
    import execution
    import nodes as comfy_nodes
    from server import PromptServer
    counts, failures = {}, set()
    lock = threading.Lock()

    @PromptServer.instance.routes.post("/h3_turbo_fixture/validate")
    async def validate(request):
        body = await request.json()
        result = await execution.validate_prompt(str(uuid.uuid4()), body["prompt"], None)
        return web.json_response({"valid": result[0], "error": result[1], "node_errors": result[3]})

    @PromptServer.instance.routes.post("/h3_turbo_fixture/reuse")
    async def reuse(request):
        state = json.loads(Path(path).read_text(encoding="utf-8"))
        finals = {entry["task"]: entry["final"] for entry in state.values() if "final" in entry}
        plugin = sys.modules[comfy_nodes.NODE_CLASS_MAPPINGS["Minimax_H3_Image"].__module__]
        def submit(body, config, **kwargs):
            model = body.get("model")
            case = {"minimax-h3-image": "minimax", "qwen-image-2.1-turbo": "qwen", "minimax-h3-comfyui-max": "video"}.get(model)
            if not case:
                raise RuntimeError("Fixture rejects unknown model")
            case += "_mixed" if case == "video" and (body.get("images") or body.get("metadata", {}).get("audio_urls")) else "_edit" if body.get("images") else "_text"
            if case not in state or "final" not in state[case]:
                raise RuntimeError("Fixture blocks all unrecorded task submissions")
            with lock:
                counts[case] = counts.get(case, 0) + 1
                if case in failures:
                    failures.remove(case)
                    raise RuntimeError("Injected test failure, no API request")
            return state[case]["task"]
        def poll(task, config, on_progress=None, **kwargs):
            if task not in finals:
                raise RuntimeError("Fixture blocks unrecorded poll")
            if on_progress:
                on_progress(100)
            return finals[task]
        plugin.submit_image_task = plugin.submit_legacy_video_task = submit
        plugin.poll_image_task = plugin.poll_legacy_video_task = poll
        plugin.upload_media = lambda *args, **kwargs: "https://example.com/fixture"
        return web.json_response({"ready": True, "recorded": len(finals)})

    @PromptServer.instance.routes.get("/h3_turbo_fixture/counts")
    async def counters(request):
        return web.json_response(dict(counts))

    @PromptServer.instance.routes.post("/h3_turbo_fixture/fail-once")
    async def fail_once(request):
        body = await request.json()
        with lock:
            failures.add(body["case"])
        return web.json_response({"ready": True})
    return {}


NODE_CLASS_MAPPINGS = install()
