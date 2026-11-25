"""Opt-in live acceptance, retaining accepted task IDs without replaying POSTs."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import contextlib
import io
import json
import os
from pathlib import Path
import re
import sys
import threading

import numpy as np
from PIL import Image, ImageDraw
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT.parent), str(ROOT.parents[1])]
from ComfyUI_Seedance import nodes
from ComfyUI_Seedance.core import h3_token, nov21_models as spec, tripo_artifacts
from ComfyUI_Seedance.core.client import _headers, _session, _decode_audio_file
from ComfyUI_Seedance.core.media import video_to_bytes


def run_suite(output, key, miora_text_normal=False):
    import av
    import folder_paths

    folder_paths.set_output_directory(str(output))
    config = {"base_url": "https://api.seedance.nz", "api_key": key}
    journal = output / "private_resume.json"
    state = json.loads(journal.read_text(encoding="utf-8")) if journal.exists() else {}
    guard, current = threading.RLock(), threading.local()

    def persist():
        partial = journal.with_suffix(".tmp")
        partial.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        partial.replace(journal)

    def emit(**value):
        with guard:
            print(json.dumps(value, ensure_ascii=False), file=sys.__stdout__, flush=True)

    with _session().get(config["base_url"] + "/v1/models", headers=_headers(key, with_json=False),
                        timeout=(8, 30), allow_redirects=False) as response:
        response.raise_for_status()
        available = {row["id"] for row in response.json()["data"]}

    def tensor(picture):
        return torch.from_numpy(np.asarray(picture, dtype=np.float32) / 255).unsqueeze(0)

    object_image = Image.new("RGB", (512, 512), "#f6f2e7")
    draw = ImageDraw.Draw(object_image)
    draw.ellipse((160, 204, 398, 325), fill="#165873")
    draw.ellipse((180, 168, 354, 350), fill="#237fbe")
    draw.ellipse((190, 145, 344, 212), fill="#173f7e")
    draw.ellipse((242, 127, 284, 173), fill="#ecb75f")
    object_image.save(output / "reference.png")
    object_ref = tensor(object_image)
    subject_image = Image.new("RGB", (640, 768), "#dce6d8")
    draw = ImageDraw.Draw(subject_image)
    draw.rounded_rectangle((140, 468, 500, 768), radius=50, fill="#22628f")
    draw.ellipse((194, 148, 446, 535), fill="#f3b985", outline="#493244", width=4)
    draw.arc((188, 117, 451, 462), 155, 370, fill="#483640", width=35)
    draw.ellipse((251, 310, 274, 335), fill="#372e30")
    draw.ellipse((366, 310, 389, 335), fill="#372e30")
    draw.arc((270, 356, 374, 441), 0, 177, fill="#843844", width=7)
    subject_image.save(output / "character.png")
    subject_ref = tensor(subject_image)

    def video_picture(name, fallback):
        file = output / (name + ".mp4")
        if not file.is_file():
            return fallback
        with av.open(str(file)) as container:
            frame = next(container.decode(video=0))
            value = frame.to_image().convert("RGB")
            value.thumbnail((768, 768))
            return tensor(value)

    vk = "A brief friendly greeting from a calm studio presenter."
    g6 = ["zhenzhen/gm-4-hydrogen", "zhenzhen/gm-4-carbon", "zhenzhen/gm-4-neon", "zhenzhen/hy-4-flash"]
    initial = [
        ("tts-flash", nodes.Gemini25TTS, {"model": spec.GEMINI_TTS[1], "prompt": "Hello. Thanks for listening.", "voice": "Puck", "instructions": "Read warmly."}),
        ("heygen-turbo", nodes.HeyGenAvatar6, {"model": spec.HEYGEN[0], "prompt": "Hello. Welcome to our studio."}),
        ("long-ecommerce", nodes.Kling4LongImage, {"model": spec.LONG_IMAGE, "image1": object_ref, "length": "short",
            "prompt": "Design a short product details page for the blue teapot in @Image1, with a hero and two feature sections."}),
        ("miora-image", nodes.Miora3D, {"model": "miora-3d", "image1": object_ref, "generate_type": "geometry", "face_count": 3000}),
        ("tts-pro", nodes.Gemini25TTS, {"model": spec.GEMINI_TTS[0], "prompt": "Hello. This is a short audio check.", "voice": "Kore"}),
        ("long-webpage", nodes.Kling4LongImage, {"model": spec.LONG_IMAGE, "skill": "webpage", "style_image": object_ref,
            "prompt": "Design a compact landing page for a pottery studio. Use @Image1 as the color reference."}),
        ("miora-text", nodes.Miora3D, {"model": "miora-3d", "prompt": "A simple round clay teapot with a handle and lid.", "generate_type": "geometry", "face_count": 3000}),
        ("h3-wf", nodes.MinimaxH3WFToken, {"model": h3_token.PROFILES["wf"][0], "image1": subject_ref, "prompt": "<Picture 1> waves once in a bright studio.", "seconds": "5"}),
        ("h3-jy", nodes.MinimaxH3JYToken, {"model": h3_token.PROFILES["jy"][0], "image1": subject_ref, "prompt": "<Picture 1> nods softly in a bright studio.", "seconds": "5"}),
    ]
    for i, model in enumerate(g6):
        kwargs = {"model": model, "max_tokens": 256, "timeout": 120}
        if i < 2:
            kwargs["prompt"] = "Reply with exactly OK."
        else:
            kwargs.update(prompt="What color is the teapot? Reply with one English word.", stream=i == 2, image1=object_ref)
        initial.append(("chat-" + str(i), nodes.SeedanceLLMAPI, kwargs))
    emit(available=sorted(({kwargs["model"] for _, _, kwargs in initial} | {spec.HEYGEN[1],
        h3_token.PROFILES["charswap"][0], h3_token.PROFILES["digital"][0]}) & available))

    def submitted(original):
        def wrapped(body, connection, **kwargs):
            with guard:
                entry = state[current.case]
                if entry.get("task"):
                    return entry["task"]
                if entry.get("started"):
                    raise RuntimeError("Prior POST may have been sent; not replaying")
                entry["started"] = True
                persist()
            task = original(body, connection, **kwargs)
            with guard:
                entry["task"] = task
                persist()
            emit(case=current.case, accepted=True)
            return task
        return wrapped

    def polled(original):
        def wrapped(task, connection, **kwargs):
            with guard:
                entry = state[current.case]
                if entry.get("final"):
                    return entry["final"]
            try:
                final = original(task, connection, **kwargs)
            except Exception as error:
                if re.match(r"^(?:Image|Audio|3D|Legacy video) task failed:", str(error), re.I):
                    with guard:
                        entry["terminal_failure"] = True
                        persist()
                raise
            with guard:
                entry["final"] = final
                persist()
            return final
        return wrapped

    families = ("audio", "image", "3d", "legacy_video")
    names = {f"{verb}_{family}_task": wrap for verb, wrap in (("submit", submitted), ("poll", polled)) for family in families}
    originals = {name: getattr(nodes, name) for name in names}

    def run(case, cls, kwargs):
        model = kwargs["model"]
        current.case = case
        if model not in available:
            emit(case=case, model=model, success=False, error="Not in the supplied key model catalog")
            return False
        with guard:
            entry = state.setdefault(case, {})
            if entry.get("proof"):
                emit(**entry["proof"])
                return True
            if entry.get("terminal_failure"):
                emit(case=case, model=model, success=False, error=entry.get("error", "Confirmed task failure"))
                return False
        emit(case=case, model=model, started=True)
        try:
            if cls is nodes.SeedanceLLMAPI:
                with guard:
                    if entry.get("started"):
                        raise RuntimeError("Prior chat POST may have been sent; not replaying")
                    entry["started"] = True
                    persist()
            result = cls().execute(api_config=config, **kwargs)["result"]
            proof = {"case": case, "model": model, "success": True}
            if cls is nodes.SeedanceLLMAPI:
                assert result[0].strip()
                if "image1" in kwargs:
                    assert "blue" in result[0].lower()
                proof.update(text_chars=len(result[0]), streaming=bool(kwargs.get("stream")))
            elif cls is nodes.Gemini25TTS:
                wave = result[0]["waveform"]
                assert torch.isfinite(wave).all() and wave.abs().max() > .001
                assert wave.shape[1] == 1 and result[0]["sample_rate"] == 24000
                proof.update(samples=wave.shape[-1], rate=24000, channels=1)
                with guard:
                    entry["audio_path"] = result[2]
            elif cls is nodes.Miora3D:
                file = Path(result[2])
                format_ = result[0].format
                meshes = len(tripo_artifacts.glb_document(file).get("meshes", [])) if format_ == "glb" else None
                assert meshes is None or meshes > 0
                proof.update(format=format_, bytes=file.stat().st_size, meshes=meshes, file_count=len(json.loads(result[5])))
            elif cls is nodes.Kling4LongImage:
                picture = result[0]
                assert torch.isfinite(picture).all() and picture.std() > .01
                proof.update(width=picture.shape[2], height=picture.shape[1])
            else:
                data, extension = video_to_bytes(result[0])
                with av.open(io.BytesIO(data)) as container:
                    stream = container.streams.video[0]
                    proof.update(width=stream.width, height=stream.height, audio=bool(container.streams.audio))
                    frames = 0
                    for frame in container.decode(video=0):
                        if not frames:
                            assert frame.to_ndarray(format="rgb24").std() > 1
                        frames += 1
                    assert frames > 0
                    proof["frames"] = frames
                assert extension == "mp4"
                (output / (case + ".mp4")).write_bytes(data)
            with guard:
                entry["proof"] = proof
                persist()
            emit(**proof)
            return True
        except Exception as error:
            message = re.sub(r"https?://[^\s\"']+|sk-[A-Za-z0-9_-]{10,}|task_[A-Za-z0-9_-]+",
                             "[REDACTED]", str(error).replace(key, "[REDACTED]"))[:600]
            with guard:
                entry["error"] = message
                persist()
            emit(case=case, model=model, success=False, error=message)
            return False

    try:
        for name, factory in names.items():
            setattr(nodes, name, factory(originals[name]))
        if miora_text_normal:
            with contextlib.redirect_stdout(io.StringIO()):
                success = run("miora-text-normal", nodes.Miora3D,
                              {"model": "miora-3d", "prompt": "A round ceramic teapot with one curved handle."})
            proof = [entry["proof"] for entry in state.values() if "proof" in entry]
            (output / "proof.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")
            return 0 if success else 1
        with contextlib.redirect_stdout(io.StringIO()), ThreadPoolExecutor(max_workers=5) as pool:
            by_case = {args[0]: pool.submit(run, *args) for args in initial}
            futures = list(by_case.values())
            flash_ok = by_case["tts-flash"].result()
            if flash_ok:
                sample = _decode_audio_file(state["tts-flash"]["audio_path"], 24000, "Acceptance")
                additional = [
                    ("heygen-audio", nodes.HeyGenAvatar6, {"model": spec.HEYGEN[1], "avatar": "Abigail Office Front", "audio": sample}),
                    ("h3-digital", nodes.MinimaxH3DigitalHumanToken, {"model": h3_token.PROFILES["digital"][0],
                        "prompt": "<Picture 1> looks forward and speaks gently.", "image1": video_picture("h3-wf", subject_ref),
                        "audio1": sample, "seconds": "3"}),
                ]
                futures.extend(pool.submit(run, *args) for args in additional)
            else:
                emit(success=False, skipped=["heygen-audio", "h3-digital"], error="Speech test did not produce a reusable WAV")
            if by_case["h3-wf"].result():
                futures.append(pool.submit(run, "h3-charswap", nodes.MinimaxH3CharSwapToken,
                    {"model": h3_token.PROFILES["charswap"][0], "image1": subject_ref, "video1": str(output / "h3-wf.mp4"),
                     "prompt": "Use <Picture 1> for the person, preserving the head motion and framing.", "duration_mode": "frames", "frames": 22}))
            else:
                emit(success=False, skipped=["h3-charswap"], error="No validated MP4 source from H3 WF")
            results = [future.result() for future in futures]
        proof = [entry["proof"] for entry in state.values() if "proof" in entry]
        (output / "proof.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0 if len(results) == 16 and all(results) else 1
    finally:
        for name, original in originals.items():
            setattr(nodes, name, original)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm-live", action="store_true", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--miora-text-normal", action="store_true",
                        help="Only check the documented default textured text-to-3D request.")
    args = parser.parse_args()
    key = os.environ.pop("SEEDANCE_API_KEY", "")
    if not key:
        raise SystemExit("SEEDANCE_API_KEY is required")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    lock = output / ".live.lock"
    with lock.open("x"):
        pass
    try:
        sys.exit(run_suite(output, key, args.miora_text_normal))
    finally:
        lock.unlink()
