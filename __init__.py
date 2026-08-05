"""
ComfyUI_Seedance - ComfyUI nodes for Seedance/HappyHorse/Wan/Kling/Hailuo/
MiniMax/Vidu video, Zhenzhen Upscaler video super-resolution, Seedream/
Dola Seedream/Qwen/Zhenzhen Image G/GK/NB image, Zhenzhen Video G/GK/V3.1,
Doubao Seed Audio, Whisper transcription, Suno music, and Midjourney APIs
(api.seedance.nz).
"""

from .nodes import (
    NODE_CLASS_MAPPINGS as BASE_NODE_CLASS_MAPPINGS,
    NODE_DISPLAY_NAME_MAPPINGS as BASE_NODE_DISPLAY_NAME_MAPPINGS,
)
from .concurrent_nodes import (
    CONCURRENT_NODE_CLASS_MAPPINGS,
    CONCURRENT_NODE_DISPLAY_NAME_MAPPINGS,
)

NODE_CLASS_MAPPINGS = {
    **BASE_NODE_CLASS_MAPPINGS,
    **CONCURRENT_NODE_CLASS_MAPPINGS,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    **BASE_NODE_DISPLAY_NAME_MAPPINGS,
    **CONCURRENT_NODE_DISPLAY_NAME_MAPPINGS,
}

WEB_DIRECTORY = "./web"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
