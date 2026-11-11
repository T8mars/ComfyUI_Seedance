"""Local-only acceptance fixture; load explicitly in an isolated test server."""

import os
from pathlib import Path
import uuid

def install():
    if not os.environ.get("SEEDANCE_TRIPO_FIXTURE_ROOT"):
        return {}
    from aiohttp import web
    import execution
    from server import PromptServer
    from comfy_api.latest import Types

    root = Path(os.environ["SEEDANCE_TRIPO_FIXTURE_ROOT"]).resolve()

    class TripoLocalFixture:
        CATEGORY = "Seedance Test"
        FUNCTION = "execute"
        RETURN_TYPES = ("FILE_3D",)

        @classmethod
        def INPUT_TYPES(cls):
            return {"required": {"model_file": (sorted(path.name for path in root.glob("*.glb")),)}}

        def execute(self, model_file):
            source = (root / model_file).resolve()
            if source.parent != root or source.suffix != ".glb":
                raise ValueError("Only the local GLB fixture directory is allowed")
            return (Types.File3D(str(source), file_format="glb"),)

    @PromptServer.instance.routes.post("/seedance_tripo_fixture/validate")
    async def validate_only(request):
        payload = await request.json()
        result = await execution.validate_prompt(str(uuid.uuid4()), payload["prompt"], None)
        return web.json_response({"valid": result[0], "error": result[1], "node_errors": result[3]})

    return {"SeedanceTripoLocalFixture": TripoLocalFixture}


NODE_CLASS_MAPPINGS = install()
