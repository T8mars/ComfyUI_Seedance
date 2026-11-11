"""Opt-in six-path real acceptance; resume accepted tasks without reposting."""

import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT.parents[1]))
from ComfyUI_Seedance import nodes
from ComfyUI_Seedance.core.media import video_to_bytes


def main(args):
    if not args.confirm_live or not os.environ.get("SEEDANCE_API_KEY"):
        raise SystemExit("Requires --confirm-live and SEEDANCE_API_KEY")
    import av
    import folder_paths
    import numpy as np
    from PIL import Image
    import torch
    directory = Path(args.output).resolve()
    folder_paths.set_output_directory(str(directory))
    private = directory/"private_resume.json"
    state = json.loads(private.read_text()) if private.exists() else {}
    proof_path = directory/"proof.json"
    proofs = json.loads(proof_path.read_text()) if proof_path.exists() else []
    current = ""
    originals = {name: getattr(nodes, name) for name in ("submit_image_task", "poll_image_task", "submit_legacy_video_task", "poll_legacy_video_task")}

    def persist():
        private.write_text(json.dumps(state, indent=2), encoding="utf-8")

    if args.retry_video_text:
        previous = state.get("video_text", {})
        if args.case != "video_text" or not previous.get("uncertain") or previous.get("task") or previous.get("ambiguous_attempts"):
            raise RuntimeError("One explicitly authorized retry requires the original uncertain text-video submit")
        state["video_text"] = {"ambiguous_attempts": [previous], "manual_retry_authorized": True}
        persist()

    def submit(original):
        def wrapped(body, config, **kwargs):
            entry = state.get(current, {})
            if entry.get("task"):
                return entry["task"]
            attempts = sum(bool(value.get("task") or value.get("uncertain")) + len(value.get("ambiguous_attempts", [])) for value in state.values())
            limit = 7 if any(value.get("manual_retry_authorized") for value in state.values()) else 6
            if entry.get("uncertain") or attempts >= limit:
                raise RuntimeError("No replay: uncertain submit or explicit creation limit")
            state[current] = {**entry, "uncertain": True, "payload": body}
            persist()
            task = original(body, config, **kwargs)
            state[current].update(task=task, uncertain=False)
            persist()
            return task
        return wrapped

    def poll(original):
        def wrapped(task, config, on_progress=None, **kwargs):
            if state[current].get("final"):
                return state[current]["final"]
            last = [0]
            def progress(value):
                if on_progress:
                    on_progress(value)
                if time.monotonic()-last[0] >= 20:
                    print(f"PROGRESS {current}: {value}%", file=sys.__stdout__, flush=True)
                    last[0] = time.monotonic()
            result = original(task, config, on_progress=progress, **kwargs)
            state[current]["final"] = result
            persist()
            return result
        return wrapped

    for name, function in originals.items():
        setattr(nodes, name, submit(function) if name.startswith("submit") else poll(function))

    def run(label, cls, **kwargs):
        nonlocal current
        current = label
        print("START "+label, flush=True)
        with contextlib.redirect_stdout(io.StringIO()):
            result = cls().execute(**kwargs)["result"]
        item = {"case": label, "success": True}
        if cls is nodes.MinimaxH3ComfyUIMax:
            data, extension = video_to_bytes(result[0])
            with av.open(io.BytesIO(data)) as container:
                stream = container.streams.video[0]
                frames = sum(1 for frame in container.decode(video=0))
                item.update(bytes=len(data), width=stream.width, height=stream.height, frames=frames, extension=extension)
            if not frames:
                raise RuntimeError("Video decoded no frames")
        else:
            image = result[0]
            if image.ndim != 4 or image.shape[0] != 1 or not torch.isfinite(image).all() or float(image.std()) <= .001:
                raise RuntimeError("Invalid or blank image")
            target = directory/(label+".png")
            Image.fromarray(np.clip(image[0].numpy()*255, 0, 255).astype(np.uint8)).save(target)
            item.update(shape=list(image.shape), saved_bytes=target.stat().st_size)
        proofs[:] = [p for p in proofs if p["case"] != label] + [item]
        proof_path.write_text(json.dumps(proofs, indent=2), encoding="utf-8")
        print(json.dumps(item), flush=True)
        return result[0]

    try:
        prompt = "A red ceramic cup beside a green leaf, clean white studio tabletop, soft shadows, product photography, no text."
        if args.case in ("all", "images"):
            image1 = run("minimax_text", nodes.MinimaxH3Image, prompt=prompt, resolution="1k", output_format="png", seed=7)
            image2 = run("qwen_text", nodes.QwenImage21Turbo, prompt="A blue ceramic teapot on a white studio tabletop, soft shadows, product photography, no text.", resolution="1k", seed=7)
        else:
            with Image.open(directory/"minimax_text.png") as source:
                image1 = torch.from_numpy(np.asarray(source.convert("RGB"), dtype=np.float32).copy()/255).unsqueeze(0)
            image2 = None
        edit = "Place the red cup from image 1 beside the blue teapot from image 2 on a clean white table. Preserve both shapes and colors."
        if args.case in ("all", "images"):
            run("minimax_edit", nodes.MinimaxH3Image, prompt=edit, resolution="1k", output_format="webp", image1=image1, image2=image2, seed=0)
            run("qwen_edit", nodes.QwenImage21Turbo, prompt=edit, resolution="720p", image1=image1, image2=image2, seed=0)
        if args.case in ("all", "video_text"):
            run("video_text", nodes.MinimaxH3ComfyUIMax, prompt="A blue ceramic teapot rotates gently on a white table. Locked camera, soft studio light.", seconds="3", resolution="480p")
        wave = torch.sin(torch.arange(24000)*(.04))*0.02
        audio = {"waveform": wave.reshape(1,1,-1), "sample_rate": 8000}
        if args.case in ("all", "video_mixed"):
            run("video_mixed", nodes.MinimaxH3ComfyUIMax, prompt="The red ceramic cup and green leaf from the reference image remain on the table. A gentle camera push in, quiet ambient sound.", seconds="3", resolution="480p", image1=image1, audio1=audio)
        return 0
    except Exception as error:
        message = re.sub(r"https?://[^\s\"']+|sk-[A-Za-z0-9]+|task_[A-Za-z0-9_-]+", "[REDACTED]", str(error))
        print(json.dumps({"case": current, "success": False, "error": type(error).__name__, "message": message[:1000]}), flush=True)
        return 1
    finally:
        for name, function in originals.items():
            setattr(nodes, name, function)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm-live", action="store_true")
    parser.add_argument("--output", required=True)
    parser.add_argument("--case", choices=["all", "images", "video_text", "video_mixed"], default="all")
    parser.add_argument("--retry-video-text", action="store_true", help="One manual retry only after renewed user authorization")
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    lock = output/".live.lock"
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(descriptor)
    try:
        sys.exit(main(args))
    finally:
        lock.unlink(missing_ok=True)
