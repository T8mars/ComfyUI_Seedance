"""Opt-in minimal live checks. Keep all generated media and task IDs outside the repo."""

from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import json
import os
from pathlib import Path
import re
import sys
from unittest.mock import patch

import av
import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT.parent), str(ROOT.parents[1])]
import folder_paths
from ComfyUI_Seedance import nodes
from ComfyUI_Seedance.core.client import _headers, _session
from ComfyUI_Seedance.core.media import video_to_bytes


def fixtures(source):
    image = np.full((288, 512, 3), 235, dtype=np.uint8)
    image[100:190, 190:280] = (20, 90, 210)
    with av.open(str(source), "w") as target:
        stream = target.add_stream("libx264", rate=24)
        stream.width, stream.height, stream.pix_fmt = 512, 288, "yuv420p"
        for i in range(72):
            frame = av.VideoFrame.from_ndarray(np.roll(image, i // 2, axis=1), format="rgb24")
            target.mux(stream.encode(frame))
        target.mux(stream.encode())
    audio = (0.04 * torch.sin(2 * torch.pi * 440 * torch.arange(72000) / 24000)).reshape(1, 1, -1)
    return torch.from_numpy(image).float().unsqueeze(0) / 255, {"waveform": audio, "sample_rate": 24000}


def main(output):
    output.mkdir(parents=True, exist_ok=False)
    folder_paths.set_output_directory(str(output))
    key = os.environ["SEEDANCE_API_KEY"]
    os.environ.setdefault("SEEDANCE_MAX_POLL_TIME", "600")
    config = {"base_url": "https://api.seedance.nz", "api_key": key}
    source = output / "source.mp4"
    image, audio = fixtures(source)
    cases = [
        (nodes.Magi2Video, dict(model="magi-2", generation_type="text", seconds=4, seed=0,
            ratio="16:9", generate_audio=False, prompt="A small blue cube slowly rotates on a plain white desk.")),
        (nodes.Magi2Video, dict(model="magi-2-global", generation_type="reference", seconds=4, seed=0,
            image1=image, video1=str(source), audio1=audio, generate_audio=True,
            prompt="Animate the blue square from the image in the style of the reference clip, with a quiet tone.")),
        (nodes.SeedanceLLMAPI, dict(model="moonshotai/kimi-k3.1-pro", max_tokens=1024,
            prompt="Reply with exactly OK.")),
        (nodes.SeedanceLLMAPI, dict(model="zhenzhen/gk-4.7", max_tokens=1024, stream=True, image1=image,
            prompt="What color is the square? Reply with one English word.")),
    ]
    with _session().get(config["base_url"] + "/v1/models", headers=_headers(key, with_json=False),
                        allow_redirects=False, timeout=(8, 30)) as response:
        response.raise_for_status()
        available = {row["id"] for row in response.json()["data"]}
    required = {kwargs["model"] for _, kwargs in cases}
    if required - available:
        raise RuntimeError(f"Missing live model IDs: {sorted(required - available)}")
    print(f"Catalog: {len(required)} requested models available", flush=True)
    submit = nodes.submit_legacy_video_task

    def journaled_submit(payload, cfg, **kwargs):
        task = submit(payload, cfg, **kwargs)
        model = payload["model"]
        (output / f"{model}.task.txt").write_text(task, encoding="utf-8")
        print(f"{model}: accepted", flush=True)
        return task

    def run(case):
        cls, kwargs = case
        model = kwargs["model"]
        try:
            result = cls().execute(api_config=config, **kwargs)["result"]
            if cls is nodes.Magi2Video:
                data, extension = video_to_bytes(result[0])
                with av.open(BytesIO(data)) as container:
                    stream = container.streams.video[0]
                    frames = sum(1 for _ in container.decode(stream))
                    if not frames or "mp4" not in container.format.name:
                        raise RuntimeError("Output is not a decodable MP4")
                    evidence = {"model": model, "decoded": True, "frames": frames, "width": stream.width,
                                "height": stream.height, "audio": bool(container.streams.audio)}
                (output / f"{model}.{extension}").write_bytes(data)
            else:
                expected = "ok" if model.startswith("moonshotai") else "blue"
                if result[0].strip().strip(".").lower() != expected:
                    raise RuntimeError("Missing expected answer in final text")
                evidence = {"model": model, "answer": expected, "stream": kwargs.get("stream", False)}
        except Exception as error:
            message = str(error).replace(key, "[REDACTED]")
            evidence = {"model": model, "error": re.sub(r"https?://\S+|sk-[\w-]+", "[REDACTED]", message)[:350]}
        print(json.dumps(evidence, ensure_ascii=False), flush=True)
        (output / f"{model.replace('/', '_')}.result.json").write_text(json.dumps(evidence), encoding="utf-8")
        return "error" not in evidence

    with patch.object(nodes, "submit_legacy_video_task", side_effect=journaled_submit):
        with ThreadPoolExecutor(max_workers=4) as pool:
            return all(list(pool.map(run, cases)))


if __name__ == "__main__":
    raise SystemExit(not main(Path(sys.argv[1]).resolve()))
