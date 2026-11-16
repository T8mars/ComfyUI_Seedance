"""Local model-refresh endpoint; credentials never appear in URLs or responses."""

import asyncio

from . import llm
from .config import get_config


def register():
    try:
        from aiohttp import web
        from server import PromptServer
    except ImportError:
        return
    server = getattr(PromptServer, "instance", None)
    if server is None or getattr(server, "seedance_llm_routes_installed", False):
        return
    server.seedance_llm_routes_installed = True

    @server.routes.post("/seedance/llm/models")
    async def models(request):
        config = None
        try:
            if request.content_length is not None and request.content_length > 16384:
                return web.json_response({"error": "Model refresh request is too large"}, status=400)
            body = await request.json()
            if not isinstance(body, dict) or set(body) - {"api_config"}:
                raise ValueError("Invalid model refresh request")
            config = get_config(body.get("api_config"))
            result = await asyncio.to_thread(llm.catalog, config, True)
            return web.json_response({"models": result, "source": llm.BASE_URL})
        except Exception as error:
            return web.json_response({"error": llm.safe_error(error, config)}, status=400)
