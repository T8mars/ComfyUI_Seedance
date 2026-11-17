"""Opt-in twelve-model acceptance with persistent no-replay submit journals."""

import argparse
import concurrent.futures
import contextlib
import io
import json
import math
import os
from pathlib import Path
import re
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT.parents[1]))
from ComfyUI_Seedance import nodes
from ComfyUI_Seedance.core import llm, seedance25_flash
from ComfyUI_Seedance.core.client import _headers, _session
from ComfyUI_Seedance.core.media import video_to_bytes


def main(args):
    if not args.confirm_live or not os.environ.get("SEEDANCE_API_KEY"):
        raise RuntimeError("Explicit --confirm-live and SEEDANCE_API_KEY are required")
    import av
    import folder_paths
    import numpy as np
    from PIL import Image, ImageDraw
    import torch

    output = Path(args.output).resolve()
    folder_paths.set_output_directory(str(output))
    config = {"base_url": "https://api.seedance.nz", "api_key": os.environ["SEEDANCE_API_KEY"]}
    private = output / "private_resume.json"
    state = json.loads(private.read_text(encoding="utf-8")) if private.exists() else {"cases": {}, "uploads": {}}
    mutex, local = threading.RLock(), threading.local()

    def persist():
        temporary = private.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(private)

    def log(value):
        with mutex:
            sys.__stdout__.write(json.dumps(value, ensure_ascii=False) + "\n")
            sys.__stdout__.flush()

    def safe(error):
        text = str(error).replace(config["api_key"], "[REDACTED]")
        return re.sub(r"https?://[^\s\"']+|sk-[A-Za-z0-9]+|task_[A-Za-z0-9_-]+", "[REDACTED]", text)[:800]

    def drawing(color, phase=0):
        image = Image.new("RGB", (640, 480), "#dde8e9")
        draw = ImageDraw.Draw(image)
        x, y = 320 + int(24 * math.sin(phase)), 245
        draw.rectangle((0, 405, 640, 480), fill="#b7c9c6")
        draw.ellipse((x-70, y-170, x+70, y-30), fill="#f5c89b", outline="#273238", width=5)
        draw.arc((x-72, y-176, x+72, y-55), 180, 355, fill="#273238", width=25)
        draw.ellipse((x-29,y-116,x-17,y-102),fill="#273238")
        draw.ellipse((x+17,y-116,x+29,y-102),fill="#273238")
        draw.arc((x-25,y-90,x+25,y-57),0,180,fill="#273238",width=4)
        draw.rounded_rectangle((x-65,y-35,x+65,y+105),radius=20,fill=color,outline="#273238",width=5)
        draw.line((x-35,y+103,x-40,y+155),fill="#273238",width=22)
        draw.line((x+35,y+103,x+40,y+155),fill="#273238",width=22)
        draw.line((x-60,y-5,x-105,y+65),fill=color,width=25)
        draw.line((x+60,y-5,x+110,y-40+int(20*math.sin(phase))),fill=color,width=25)
        return image

    reference_path = output / "reference.png"
    drawing("#148bb5").save(reference_path)
    reference = torch.from_numpy(np.asarray(drawing("#148bb5"), dtype=np.float32) / 255).unsqueeze(0)
    last = torch.from_numpy(np.asarray(drawing("#148bb5", 1.2), dtype=np.float32) / 255).unsqueeze(0)
    audio = {"waveform": (torch.sin(torch.arange(48000) * (2 * math.pi * 440 / 24000)) * .04).reshape(1, 1, -1), "sample_rate": 24000}
    source = output / "source.mp4"
    if not source.exists():
        with av.open(str(source), "w") as container:
            stream = container.add_stream("libx264", rate=24)
            stream.width, stream.height, stream.pix_fmt = 640, 480, "yuv420p"
            sound = container.add_stream("aac", rate=24000)
            sound.layout = "mono"
            for index in range(72):
                frame = av.VideoFrame.from_image(drawing("#b64050", index / 12))
                for packet in stream.encode(frame):
                    container.mux(packet)
            for packet in stream.encode():
                container.mux(packet)
            samples = (np.sin(np.arange(72000) * (2 * math.pi * 220 / 24000)) * .04).astype(np.float32).reshape(1, -1)
            frame = av.AudioFrame.from_ndarray(samples, format="fltp", layout="mono")
            frame.sample_rate, frame.pts = 24000, 0
            for packet in sound.encode(frame):
                container.mux(packet)
            for packet in sound.encode():
                container.mux(packet)

    classes = {
        "minimax-h3-comfyui-charswap": nodes.MinimaxH3ComfyUICharSwap,
        "minimax-h3-comfyui-wuxi": nodes.MinimaxH3ComfyUIWuxi,
        "minimax-h3-comfyui-max-10020": nodes.MinimaxH3ComfyUIWF,
        "minimax-h3-comfyui-max-10021": nodes.MinimaxH3ComfyUISelfLift,
    }
    models = ["doubao-seed-tts-2.0", "zhenzhen-fb-5.2", *seedance25_flash.MODELS, *classes]
    if len(models) != 12:
        raise RuntimeError("Unexpected live model set")
    response = _session().get(config["base_url"] + "/v1/models", headers=_headers(config["api_key"], with_json=False), timeout=(8, 30), allow_redirects=False)
    response.raise_for_status()
    available = {item["id"] for item in response.json()["data"]}
    response.close()
    log({"catalog_verified": True, "available_requested_models": [model for model in models if model in available], "missing": [model for model in models if model not in available]})
    originals = {name: getattr(nodes, name) for name in ("submit_task", "poll_task", "submit_legacy_video_task", "poll_legacy_video_task", "submit_audio_task", "poll_audio_task", "upload_media")}

    def submit(original):
        def wrapped(body, connection, **kwargs):
            model = local.model
            with mutex:
                entry = state["cases"].setdefault(model, {})
                if entry.get("task"):
                    return entry["task"]
                if entry.get("started"):
                    raise RuntimeError("Uncertain prior submit: no automatic replay")
                if sum(bool(item.get("started")) for item in state["cases"].values()) >= 12:
                    raise RuntimeError("Twelve-request creation cap reached")
                entry.update(started=True, payload=body)
                persist()
            task = original(body, connection, **kwargs)
            with mutex:
                entry.update(task=task)
                persist()
            log({"model": model, "submitted": True})
            return task
        return wrapped

    def poll(original):
        def wrapped(task, connection, on_progress=None, **kwargs):
            with mutex:
                final = state["cases"][local.model].get("final")
            if final:
                return final
            last_log = [0]
            def progress(value):
                if on_progress:
                    on_progress(value)
                if time.monotonic() - last_log[0] > 45:
                    log({"model": local.model, "progress": value})
                    last_log[0] = time.monotonic()
            final = original(task, connection, on_progress=progress, **kwargs)
            with mutex:
                state["cases"][local.model]["final"] = final
                persist()
            return final
        return wrapped

    def upload(data, filename, mime, connection, **kwargs):
        import hashlib
        digest = hashlib.sha256(data).hexdigest()
        with mutex:
            cached = state["uploads"].get(digest)
            if cached and time.time() - cached["time"] < 20 * 3600:
                return cached["url"]
            url = originals["upload_media"](data, filename, mime, connection, **kwargs)
            state["uploads"][digest] = {"url": url, "time": time.time()}
            persist()
            return url

    for name, function in originals.items():
        setattr(nodes, name, upload if name == "upload_media" else submit(function) if name.startswith("submit") else poll(function))

    def run(model):
        local.model = model
        with mutex:
            if state["cases"].get(model, {}).get("proof"):
                log({"model": model, "reused_success": True})
                return True
        if model not in available:
            log({"model": model, "success": False, "error": "Model not listed for supplied API key; no task created"})
            return False
        try:
            log({"model": model, "started": True})
            if model == "zhenzhen-fb-5.2":
                with mutex:
                    entry = state["cases"].setdefault(model, {})
                    if entry.get("started"):
                        raise RuntimeError("Prior chat request may have been transmitted; do not replay")
                    entry["started"] = True
                    persist()
                result = nodes.SeedanceLLMAPI().execute(model=model, prompt="Reply with exactly OK.", max_tokens=256, timeout=180, api_config=config)["result"]
                proof = {"model": model, "success": bool(result[0].strip()), "text_characters": len(result[0]), "history_messages": len(json.loads(result[2]))}
            elif model == "doubao-seed-tts-2.0":
                result = nodes.DoubaoSeedTTS20().execute(prompt="\u4f60\u597d\uff0c\u4eca\u5929\u7684\u6d4b\u8bd5\u5df2\u7ecf\u5b8c\u6210\u3002", context_texts="\u8bf7\u7528\u81ea\u7136\u4eb2\u5207\u7684\u8bed\u6c14\u8bf4\u3002", speaker="zh_female_vv_uranus_bigtts", api_config=config)["result"]
                wave = result[0]["waveform"]
                proof = {"model": model, "success": bool(torch.isfinite(wave).all()) and float(wave.abs().max()) > .001,
                         "sample_rate": result[0]["sample_rate"], "samples": wave.shape[-1], "saved_bytes": Path(result[2]).stat().st_size}
            else:
                if model in seedance25_flash.MODELS:
                    kwargs = {"model": model, "prompt": "A friendly blue toy puppet waves gently in a bright studio. Locked camera, consistent character design, no text.", "seconds": "4", "resolution": "480p", "ratio": "adaptive"}
                    if model.endswith("-i2v"):
                        kwargs.update(image1=reference, image2=last)
                    elif model.endswith("-multi"):
                        kwargs.update(image1=reference, video1=str(source), audio1=audio)
                    cls = nodes.Seedance25Video
                else:
                    cls = classes[model]
                    kwargs = {"prompt": "<Picture 1> is the main character. Preserve the blue outfit and cheerful face. Animate a gentle wave with the reference motion.", "seconds": "3" if "1002" in model else "5", "resolution": "480p", "ratio": "auto" if "charswap" in model else "16:9", "image1": reference, "seed": 7}
                    if "charswap" in model:
                        kwargs.update(video1=str(source), duration_mode="frames", frames=22)
                    else:
                        kwargs["audio1"] = audio
                        if model.endswith("wuxi"):
                            kwargs["video1"] = str(source)
                result = cls().execute(api_config=config, **kwargs)["result"]
                data, extension = video_to_bytes(result[0])
                with av.open(io.BytesIO(data)) as container:
                    stream = container.streams.video[0]
                    frames, varied = 0, False
                    for frame in container.decode(video=0):
                        frames += 1
                        if frames == 1:
                            varied = float(frame.to_ndarray(format="rgb24").std()) > 1
                    proof = {"model": model, "success": frames > 0 and varied, "bytes": len(data), "width": stream.width, "height": stream.height, "frames": frames, "has_audio_stream": bool(container.streams.audio)}
                (output / (model + "." + extension)).write_bytes(data)
            if not proof["success"]:
                raise RuntimeError("Output decode or nonblank validation failed")
            with mutex:
                state["cases"].setdefault(model, {})["proof"] = proof
                persist()
                (output / "proof.json").write_text(json.dumps([item["proof"] for item in state["cases"].values() if item.get("proof")], indent=2), encoding="utf-8")
            log(proof)
            return True
        except Exception as error:
            log({"model": model, "success": False, "error": type(error).__name__, "message": safe(error)})
            with mutex:
                state["cases"].setdefault(model, {})["error"] = safe(error)
                persist()
            return False

    try:
        with contextlib.redirect_stdout(io.StringIO()):
            chosen = models if args.case == "all" else [args.case]
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(run, chosen))
        return 0 if all(results) else 1
    finally:
        for name, function in originals.items():
            setattr(nodes, name, function)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm-live", action="store_true")
    parser.add_argument("--output", required=True)
    parser.add_argument("--case", default="all")
    args = parser.parse_args()
    directory = Path(args.output).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory / ".live.lock"
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(descriptor)
    try:
        sys.exit(main(args))
    finally:
        lock.unlink(missing_ok=True)
