"""
ComfyUI_Seedance - ComfyUI nodes for Seedance/HappyHorse/Wan video,
Zhenzhen Upscaler video super-resolution, Seedream/Dola Seedream image,
and Doubao Seed Audio APIs (api.seedance.nz).
"""

from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

WEB_DIRECTORY = "./web"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
