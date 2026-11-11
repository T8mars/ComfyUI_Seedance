"""Opt-in eight-model live acceptance with two draft sources and resumable IDs."""

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
from ComfyUI_Seedance.core import client
from ComfyUI_Seedance.core.media import video_to_bytes


def main(args):
    if not args.confirm_live or not os.getenv("SEEDANCE_API_KEY"):
        raise SystemExit("Requires --confirm-live and SEEDANCE_API_KEY")
    import av
    import folder_paths
    directory = Path(args.output).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    folder_paths.set_output_directory(str(directory))
    private = directory / "private_resume.json"
    state = json.loads(private.read_text()) if private.exists() else {}
    current = ""
    proof_path = directory / "proof.json"
    proof = json.loads(proof_path.read_text()) if proof_path.exists() else []
    originals = {name: getattr(nodes, name) for name in ("submit_task", "poll_task", "submit_image_task", "poll_image_task")}

    if args.retry_failed_enhance:
        if not args.video_region:
            raise RuntimeError("A single --video-region is required for an explicit failed-task retry")
        case = args.video_region + "_enhance"
        previous = state.get(case, {})
        if not previous.get("task"):
            raise RuntimeError("No prior enhancement exists to verify")
        with contextlib.redirect_stdout(io.StringIO()):
            config = nodes.get_config()
        response = client._session().get(config["base_url"]+"/v1/videos/"+previous["task"],
            headers=client._headers(config["api_key"]), timeout=60)
        response.raise_for_status()
        terminal = response.json()
        if terminal.get("status") != "failed" or str(terminal.get("error", {}).get("code")) != "1010":
            raise RuntimeError("Retry refused: prior task is not a confirmed terminal 1010 failure")
        history = previous.get("failed_attempts", []) + [{"task": previous["task"], "terminal": terminal}]
        state[case] = {"failed_attempts": history}
        private.write_text(json.dumps(state, indent=2), encoding="utf-8")
        print("Confirmed terminal 1010; one explicit enhancement retry authorized for this test run", flush=True)

    def persist():
        private.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def submit(original):
        def wrapped(payload, config, **kwargs):
            previous = state.get(current, {})
            if previous.get("task"):
                return previous["task"]
            created = sum(bool(value.get("task")) + len(value.get("failed_attempts", [])) for value in state.values())
            if previous.get("uncertain") or created >= args.max_creations:
                raise RuntimeError("No replay: uncertain submission or explicit creation limit reached")
            state[current] = {"uncertain": True, "failed_attempts": previous.get("failed_attempts", [])}
            persist()
            task = original(payload, config, **kwargs)
            state[current].update(task=task, uncertain=False)
            persist()
            return task
        return wrapped

    def poll(original):
        def wrapped(task, config, on_progress=None, **kwargs):
            if state[current].get("final"):
                return state[current]["final"]
            last = [-1, 0]
            def progress(value):
                if on_progress:
                    on_progress(value)
                if value != last[0] and time.monotonic() - last[1] > 15:
                    print(f"PROGRESS {current}: {value}%", file=sys.__stdout__, flush=True)
                    last[:] = [value, time.monotonic()]
            result = original(task, config, on_progress=progress, **kwargs)
            state[current]["final"] = result
            persist()
            return result
        return wrapped

    for name, function in originals.items():
        setattr(nodes, name, submit(function) if name.startswith("submit") else poll(function))

    def run(label, cls, kind, **kwargs):
        nonlocal current
        current = label
        print("START " + label, flush=True)
        with contextlib.redirect_stdout(io.StringIO()):
            result = cls().execute(**kwargs)["result"]
        item = {"case": label, "model": kwargs["model"], "success": True}
        if kind == "video":
            data, extension = video_to_bytes(result[0])
            with av.open(io.BytesIO(data)) as container:
                stream = container.streams.video[0]
                count = sum(1 for _ in container.decode(video=0))
                item.update(bytes=len(data), width=stream.width, height=stream.height, frames=count,
                            extension=extension, major_brand=container.metadata.get("major_brand", ""))
            if count == 0 or label.endswith("enhance") and min(item["width"], item["height"]) < 1080:
                raise RuntimeError("Empty video or enhancement did not reach native1080p")
        elif kind == "layer":
            paths = json.loads(result[6])
            item.update(images=result[3], bytes=[Path(path).stat().st_size for path in paths],
                        shapes=[list(image.shape) for image in result[0]], has_layers_metadata=bool(json.loads(result[7])))
            if result[3] < 2 or len(result[0]) != result[3] or len(result[1]) != result[3] or len(paths) != result[3]:
                raise RuntimeError("Layer result did not preserve all multiple images/masks/files")
        else:
            image, mask = result[0], result[4]
            item.update(bytes=Path(result[5]).stat().st_size, shape=list(image.shape), transparent_pixels=int((mask > 0).sum()))
            if kwargs.get("background") == "transparent" and (image.shape[-1] != 4 or not item["transparent_pixels"]):
                raise RuntimeError("Requested transparent PNG was not returned with transparent pixels")
        proof[:] = [previous for previous in proof if previous["case"] != label] + [item]
        proof_path.write_text(json.dumps(proof, indent=2), encoding="utf-8")
        print(json.dumps(item), flush=True)
        return result

    try:
        for global_ in (() if args.skip_images else (False, True)):
            label = "global" if global_ else "domestic"
            prefix = "dola-seedream-5.5" if global_ else "seedream-v5.5"
            generated = run(label + "_t2i", nodes.Seedream55Image, "image", model=prefix+"-t2i",
                prompt="Three separate objects with space between them: a red ceramic mug, a blue cube, and a green leaf. Isolated on transparent background, clean product photography, no text.",
                resolution="1k", output_format="png", background="transparent")
            run(label + "_i2i", nodes.Seedream55Image, "image", model=prefix+"-i2i", image1=generated[0],
                prompt="Keep the three objects and their layout. Change the blue cube to a yellow cube, use a plain white opaque background.",
                resolution="1k", output_format="jpeg", background="opaque")
            run(label + "_layers", nodes.Seedream55LayerDecomposition, "layer", model=prefix+"-layer-decomposition",
                image=generated[0], prompt="Separate the foreground objects from the background.", resolution="1k",
                output_format="png", max_images=2, text_recognition=True)
        for global_ in (False, True):
            label = "global" if global_ else "domestic"
            if args.video_region and args.video_region != label:
                continue
            prefix = "seedance-2.5-" + ("global-" if global_ else "") + "standard-"
            draft = run(label + "_draft", nodes.Seedance25Video, "video", model=prefix+"t2v", draft=True,
                        prompt="A small blue ball rolls slowly across a clean white tabletop. Locked camera, natural soft daylight.",
                        seconds="4", resolution="480p", ratio="16:9", generate_audio=False, seed=17)
            run(label + "_enhance", nodes.Seedance25DraftToVideo, "video", model=prefix+"draft-to-video",
                draft_task_id=draft[2], output_format="mov" if global_ else "mp4", return_last_frame=global_)
        return 0
    except Exception as exc:
        message = re.sub(r"https?://[^\s\"']+|sk-[A-Za-z0-9]+|task_[A-Za-z0-9_-]+", "[REDACTED]", str(exc))
        print(json.dumps({"case": current, "success": False, "error": type(exc).__name__, "message": message[:1200]}), flush=True)
        return 1
    finally:
        for name, function in originals.items():
            setattr(nodes, name, function)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm-live", action="store_true")
    parser.add_argument("--output", required=True)
    parser.add_argument("--video-region", choices=["domestic", "global"])
    parser.add_argument("--skip-images", action="store_true")
    parser.add_argument("--retry-failed-enhance", action="store_true")
    parser.add_argument("--max-creations", type=int, choices=[10, 11], default=10)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    lock = output / ".live.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise SystemExit("Another run owns this resume directory; verify its process before removing a stale lock")
    os.close(descriptor)
    try:
        sys.exit(main(args))
    finally:
        lock.unlink(missing_ok=True)
