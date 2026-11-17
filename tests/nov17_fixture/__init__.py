"""Explicit isolated-server queue validation; never starts API generation."""

import os
import uuid


def install():
    if os.getenv("SEEDANCE_NOV17_FIXTURE") != "1":
        return {}
    from aiohttp import web
    import execution
    from server import PromptServer

    @PromptServer.instance.routes.post("/seedance_nov17_fixture/validate")
    async def validate(request):
        result = await execution.validate_prompt(str(uuid.uuid4()), (await request.json())["prompt"], None)
        return web.json_response({"valid": result[0], "error": result[1], "node_errors": result[3]})

    return {}


NODE_CLASS_MAPPINGS = install()
