"""Opt-in minimal node-path tests; credentials are read only from the environment."""

import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import re
import sys
import time

import torch
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT.parents[1]))
from ComfyUI_Seedance import nodes
from ComfyUI_Seedance.core import flash_video
from ComfyUI_Seedance.core.media import video_to_bytes


def reference():
    import numpy as np
    image = Image.new("RGB", (512, 512), "#e3f5ed")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((156, 60, 356, 235), 30, fill="#2586c8")
    draw.rectangle((180, 100, 332, 180), fill="#17232b")
    draw.ellipse((205, 128, 225, 148), fill="white")
    draw.ellipse((287, 128, 307, 148), fill="white")
    draw.rounded_rectangle((180, 245, 332, 410), 20, fill="#2586c8")
    draw.rectangle((220, 270, 292, 305), fill="#f1ca55")
    draw.rectangle((120, 260, 170, 385), fill="#2586c8")
    draw.rectangle((342, 260, 392, 385), fill="#2586c8")
    draw.rectangle((190, 410, 240, 470), fill="#17232b")
    draw.rectangle((272, 410, 322, 470), fill="#17232b")
    return torch.from_numpy(np.asarray(image).copy()).float().unsqueeze(0) / 255


def run(args):
    if not args.confirm_live or not os.environ.get("SEEDANCE_API_KEY"):
        raise SystemExit("Requires --confirm-live and SEEDANCE_API_KEY")
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    os.environ["SEEDANCE_OUTPUT_DIR"] = str(output)
    import folder_paths
    folder_paths.set_output_directory(str(output))
    folder_paths.set_temp_directory(str(output / "temp"))
    (output / "temp").mkdir(exist_ok=True)
    proof = []
    cases = []
    if args.group == "images":
        for resolution, version in (("2k", "flare"), ("4k", "sunburst")):
            cases.append(("g26_" + resolution, nodes.ZhenzhenImageG26(), {
                "prompt": "A single white ceramic cup on a clean mint tabletop, centered studio photograph, no text.",
                "resolution": resolution, "version": version, "quality": "low", "output_format": "png", "size": "1:1"}))
        cases.append(("g26_gif", nodes.ZhenzhenImageG26(), {
            "mode": "gif", "prompt": "A red ball bounces up and down on a white floor, seamless looping animated GIF, locked camera.",
            "resolution": "1k", "quality": "low"}))
    else:
        for model, cls in ((flash_video.KLING_MODEL, nodes.Kling4Omni),
                           (flash_video.OMNI_MODEL, nodes.ZhenzhenVideoGOmni12FlashLowprice)):
            for mode in ("text", "images", "video"):
                kwargs = {"prompt": "A small original blue toy robot slowly raises one arm in a clean mint studio. Locked camera, gentle natural motion.",
                          "seconds": 3, "resolution": "720p" if model == flash_video.KLING_MODEL else "360p", "seed": 42}
                if model == flash_video.KLING_MODEL:
                    kwargs.update(model=model, ratio="16:9")
                else:
                    kwargs["aspect_ratio"] = "16:9"
                if mode == "images":
                    kwargs["image1"] = reference()
                cases.append((model + "_" + mode, cls(), kwargs))
    last_video = None
    for label, node, kwargs in cases:
        if label.endswith("_video"):
            if last_video is None:
                raise RuntimeError("No successful local video available for reference test")
            kwargs["video1"] = last_video
        print("START " + label, flush=True)
        start = time.monotonic()
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                result = node.execute(**kwargs)
            values = result["result"]
            item = {"case": label, "success": True, "seconds_elapsed": round(time.monotonic() - start, 2)}
            if args.group == "images":
                tensor = values[0]
                if not torch.isfinite(tensor).all() or tensor.numel() == 0:
                    raise RuntimeError("Invalid decoded image tensor")
                item["shape"] = list(tensor.shape)
                with Image.open(values[4]) as decoded:
                    item.update(format=decoded.format, frames=getattr(decoded, "n_frames", 1), bytes=Path(values[4]).stat().st_size)
                    if label.endswith("gif") and (decoded.format != "GIF" or item["frames"] < 2):
                        raise RuntimeError("Expected an actual animated GIF")
            else:
                import av
                data, _ = video_to_bytes(values[0])
                with av.open(io.BytesIO(data)) as container:
                    stream = container.streams.video[0]
                    frames = sum(1 for _ in container.decode(video=0))
                    item.update(width=stream.width, height=stream.height, frames=frames, bytes=len(data))
                if not frames:
                    raise RuntimeError("Empty decoded video")
                last_video = values[0]
            proof.append(item)
            print(json.dumps(item), flush=True)
        except Exception as error:
            # Do not print API responses, runtime IDs or signed URLs.
            message = re.sub(r"https?://[^\s\"']+", "[URL]", str(error))
            message = re.sub(r"sk-[A-Za-z0-9]+|task_[A-Za-z0-9_-]+", "[REDACTED]", message)
            failure = {"case": label, "success": False, "error_type": type(error).__name__, "message": message[:2000]}
            print(json.dumps(failure), flush=True)
            proof.append(failure)
            (output / (args.group + "_proof.json")).write_text(json.dumps(proof, indent=2), encoding="utf-8")
            raise SystemExit(1)
        (output / (args.group + "_proof.json")).write_text(json.dumps(proof, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm-live", action="store_true")
    parser.add_argument("--group", choices=("images", "videos"), required=True)
    parser.add_argument("--output", required=True)
    run(parser.parse_args())
