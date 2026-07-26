"""
ComfyUI_Seedance - ComfyUI nodes for Seedance/HappyHorse/Wan/Kling/Hailuo/
Vidu video, Zhenzhen Upscaler video super-resolution, Seedream/Dola Seedream/
Zhenzhen Image G/GK/NB image, Zhenzhen Video G/GK/V3.1, Doubao Seed Audio,
Whisper transcription, Suno music, and Midjourney APIs (api.seedance.nz).
"""

from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

WEB_DIRECTORY = "./web"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
