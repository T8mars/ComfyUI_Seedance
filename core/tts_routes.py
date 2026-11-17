"""Serve the bundled public voice catalog without credentials or network calls."""


def register():
    try:
        from aiohttp import web
        from server import PromptServer
    except ImportError:
        return
    instance = getattr(PromptServer, "instance", None)
    if instance is None or getattr(instance, "_seedance_tts_routes", False):
        return
    from .doubao_tts import CATALOG

    @instance.routes.get("/seedance/doubao/voices")
    async def voices(request):
        return web.json_response(CATALOG)

    instance._seedance_tts_routes = True
