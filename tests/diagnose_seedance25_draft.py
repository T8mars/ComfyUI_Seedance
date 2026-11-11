"""Opt-in controlled draft enhancement checks; reuses an existing completed source."""

import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import re
import sys

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
    directory = Path(args.directory).resolve()
    original = json.loads((directory / "private_resume.json").read_text())
    source = original["domestic_draft"]["task"]
    state_path = directory / "private_draft_diagnostics.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    if args.case == "fresh-node-default":
        if not state.get("fresh-source", {}).get("final"):
            raise RuntimeError("A completed fresh-source test is required")
        source = state["fresh-source"]["task"]
    item = state.setdefault(args.case, {})
    folder_paths.set_output_directory(str(directory))
    with contextlib.redirect_stdout(io.StringIO()):
        config = nodes.get_config()

    def save():
        state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    metadata = {"draft_task_id": source}
    if args.case == "matched-options":
        metadata.update(output_format="mov", return_last_frame=True)
    payload = {"model": nodes.Seedance25DraftToVideo.MODELS[0], "metadata": metadata}
    original_submit, original_poll = nodes.submit_task, nodes.poll_task

    def submit(body, connection, **kwargs):
        if item.get("task"):
            return item["task"]
        if item.get("uncertain") or sum(bool(value.get("task")) for value in state.values()) >= 3:
            raise RuntimeError("No replay: uncertain request or three controlled-test limit")
        item.update(uncertain=True, payload=body)
        save()
        task = original_submit(body, connection, **kwargs)
        item.update(task=task, uncertain=False)
        save()
        return task

    def poll(task, connection, on_progress=None, **kwargs):
        if item.get("final"):
            return item["final"]
        last = [-1]
        def progress(value):
            if on_progress:
                on_progress(value)
            if value != last[0]:
                print(f"PROGRESS {args.case}: {value}%", file=sys.__stdout__, flush=True)
                last[0] = value
        final = original_poll(task, connection, on_progress=progress, **kwargs)
        item["final"] = final
        save()
        return final

    try:
        print("START controlled domestic " + args.case, flush=True)
        with contextlib.redirect_stdout(io.StringIO()):
            if args.case in ("node-default", "fresh-node-default", "fresh-source"):
                nodes.submit_task, nodes.poll_task = submit, poll
                if args.case == "fresh-source":
                    result = nodes.Seedance25Video().execute(model=nodes.SEEDANCE25_T2V_MODELS[0],
                        prompt="A small blue ball rolls slowly across a clean white tabletop. Locked camera, natural soft daylight.",
                        seconds="4", resolution="480p", ratio="16:9", draft=True, seed=-1, api_config=config)["result"]
                else:
                    result = nodes.Seedance25DraftToVideo().execute(draft_task_id=source, api_config=config)["result"]
                video = result[0]
            else:
                task = submit(payload, config)
                final = poll(task, config)
                video, _path = client.download_video_with_path(client.extract_video_url(final),
                    file_extension=metadata.get("output_format", "mp4"))
        data, extension = video_to_bytes(video)
        with av.open(io.BytesIO(data)) as container:
            stream = container.streams.video[0]
            frames = sum(1 for _ in container.decode(video=0))
            proof = {"case": args.case, "success": True, "bytes": len(data), "width": stream.width,
                     "height": stream.height, "frames": frames, "extension": extension,
                     "major_brand": container.metadata.get("major_brand", "")}
        if not frames or (args.case != "fresh-source" and min(proof["width"], proof["height"]) < 1080):
            raise RuntimeError("Result was not a nonempty native1080p video")
        item["proof"] = proof
        save()
        print(json.dumps(proof), flush=True)
        return 0
    except Exception as exc:
        if item.get("task"):
            try:
                response = client._session().get(config["base_url"]+"/v1/videos/"+item["task"],
                    headers=client._headers(config["api_key"]), timeout=60)
                response.raise_for_status()
                item["last_response"] = response.json()
                save()
            except Exception:
                pass
        message = re.sub(r"https?://[^\s\"']+|task_[A-Za-z0-9_-]+|sk-[A-Za-z0-9]+", "[REDACTED]", str(exc))
        print(json.dumps({"case": args.case, "success": False, "error": type(exc).__name__, "message": message[:1000]}), flush=True)
        return 1
    finally:
        nodes.submit_task, nodes.poll_task = original_submit, original_poll


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm-live", action="store_true")
    parser.add_argument("--directory", required=True)
    parser.add_argument("--case", choices=["minimal", "matched-options", "node-default", "fresh-source", "fresh-node-default"], required=True)
    args = parser.parse_args()
    lock = Path(args.directory) / ".diagnostics.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise SystemExit("A diagnostic run already owns this directory")
    os.close(descriptor)
    try:
        sys.exit(main(args))
    finally:
        lock.unlink(missing_ok=True)
