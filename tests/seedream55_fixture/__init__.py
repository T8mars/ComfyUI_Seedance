"""Isolated ComfyUI acceptance only: reuse completed results, never create tasks."""

import json
import os
from pathlib import Path
import sys
import threading
import uuid


def install():
    state_path = os.environ.get("SEEDANCE55_RESUME_PATH")
    if not state_path:
        return {}
    from aiohttp import web
    import execution
    import nodes as comfy_nodes
    from server import PromptServer

    counts = {}
    failures = set()
    lock = threading.Lock()

    @PromptServer.instance.routes.post("/seedance55_fixture/validate")
    async def validate_only(request):
        payload = await request.json()
        result = await execution.validate_prompt(str(uuid.uuid4()), payload["prompt"], None)
        return web.json_response({"valid": result[0], "error": result[1], "node_errors": result[3]})

    @PromptServer.instance.routes.post("/seedance55_fixture/reuse")
    async def reuse(request):
        state = json.loads(Path(state_path).read_text(encoding="utf-8"))
        by_task = {item["task"]: item["final"] for item in state.values() if "final" in item}
        model_cases = {}
        for region, seedream, seedance in (("domestic", "seedream-v5.5", "seedance-2.5-standard"),
                                          ("global", "dola-seedream-5.5", "seedance-2.5-global-standard")):
            model_cases.update({seedream+"-t2i": region+"_t2i", seedream+"-i2i": region+"_i2i",
                                seedream+"-layer-decomposition": region+"_layers",
                                seedance+"-t2v": region+"_draft", seedance+"-draft-to-video": region+"_enhance"})
        plugin = sys.modules[comfy_nodes.NODE_CLASS_MAPPINGS["Seedream_5_5_Image"].__module__]

        def submit(payload, config, **kwargs):
            case = model_cases.get(payload.get("model"))
            if case not in state or "final" not in state[case]:
                raise RuntimeError("Fixture blocks all unrecorded task submissions")
            if case.endswith("_draft") and payload.get("metadata", {}).get("draft") is not True:
                raise RuntimeError("Fixture source must explicitly request a draft")
            if case.endswith("_enhance") and payload.get("metadata", {}).get("draft_task_id") != state[case.replace("_enhance", "_draft")]["task"]:
                raise RuntimeError("Enhancement must receive its region's actual completed draft ID")
            with lock:
                counts[case] = counts.get(case, 0) + 1
                if case in failures:
                    failures.remove(case)
                    raise RuntimeError("Injected acceptance failure; no API call was made")
            return state[case]["task"]

        def poll(task, config, on_progress=None, **kwargs):
            if task not in by_task:
                raise RuntimeError("Fixture blocks all unrecorded polls")
            if on_progress:
                on_progress(100)
            return by_task[task]

        plugin.submit_task = plugin.submit_image_task = submit
        plugin.poll_task = plugin.poll_image_task = poll
        plugin.upload_media = lambda *args, **kwargs: "https://example.com/fixture.png"
        return web.json_response({"ready": True, "recorded_cases": len(by_task)})

    @PromptServer.instance.routes.get("/seedance55_fixture/counts")
    async def counters(request):
        return web.json_response(dict(counts))

    @PromptServer.instance.routes.post("/seedance55_fixture/fail-once")
    async def fail_once(request):
        payload = await request.json()
        with lock:
            failures.add(payload["case"])
        return web.json_response({"armed": True})

    return {}


NODE_CLASS_MAPPINGS = install()
