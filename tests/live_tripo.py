"""Opt-in three-task Tripo chain with private, key-free resume state."""

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
from ComfyUI_Seedance.core import tripo_artifacts


def main(args):
    if not args.confirm_live or not os.environ.get("SEEDANCE_API_KEY"):
        raise SystemExit("Requires --confirm-live and SEEDANCE_API_KEY")
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    import folder_paths
    folder_paths.set_output_directory(str(output))
    state_path = output / "private_resume.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    proof = []
    current = ""
    original_submit, original_poll = nodes.submit_3d_task, nodes.poll_3d_task

    def save_state():
        state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def submit(payload, config, **kwargs):
        previous = state.get(current, {})
        if previous.get("task"):
            return previous["task"]
        if previous.get("uncertain") or sum(bool(value.get("task")) for value in state.values()) >= 3:
            raise RuntimeError("Creation limit reached or an earlier submission was uncertain; no replay")
        state[current] = {"uncertain": True}
        save_state()
        task = original_submit(payload, config, **kwargs)
        state[current] = {"task": task}
        save_state()
        return task

    def poll(task, config, on_progress=None, **kwargs):
        if state[current].get("final"):
            return state[current]["final"]
        last = [None, 0]

        def progress(value):
            if on_progress:
                on_progress(value)
            if value != last[0] and time.monotonic() - last[1] > 10:
                print(f"PROGRESS {current}: {value}%", file=sys.__stdout__, flush=True)
                last[:] = [value, time.monotonic()]
        final = original_poll(task, config, on_progress=progress, **kwargs)
        state[current]["final"] = final
        save_state()
        return final

    nodes.submit_3d_task, nodes.poll_3d_task = submit, poll
    generated = segmented = None
    try:
        for label, cls in (("generate", nodes.TripoGenerate), ("segment", nodes.TripoMesh), ("complete", nodes.TripoMesh)):
            current = label
            if label == "generate":
                kwargs = {"model": "tripo-p-p1-text-to-3d", "prompt": "A simple low-poly toy robot with a large square head, short torso, two separate arms and two legs, standing upright.",
                          "face_limit": 1000, "texture": "false", "pbr": "false"}
            elif label == "segment":
                kwargs = {"model": "tripo-mesh-segment-v1", "model_url": generated[1]}
            else:
                names = json.loads(segmented[6])
                parts = [name for name in names if name.startswith("tripo_part_")]
                if not segmented[4] or not parts:
                    raise RuntimeError("Segmentation did not provide a Tripo ID and selectable parts")
                kwargs = {"model": "tripo-mesh-complete", "tripo_segment_task_id": segmented[4],
                          "completion_mode": "quick_cap", "part_names": json.dumps(parts[:1])}
            print("START " + label, flush=True)
            start = time.monotonic()
            with contextlib.redirect_stdout(io.StringIO()):
                result = cls().execute(**kwargs)["result"]
            document = tripo_artifacts.glb_document(result[2])
            if not document.get("meshes"):
                raise RuntimeError("Result GLB has no meshes")
            item = {"case": label, "success": True, "seconds_elapsed": round(time.monotonic()-start, 2),
                    "bytes": Path(result[2]).stat().st_size, "meshes": len(document["meshes"]),
                    "named_nodes": len(json.loads(result[6])), "files": len(json.loads(result[5])),
                    "has_tripo_id": bool(result[4])}
            proof.append(item)
            print(json.dumps(item), flush=True)
            (output / "proof.json").write_text(json.dumps(proof, indent=2), encoding="utf-8")
            if label == "generate":
                generated = result
            elif label == "segment":
                segmented = result
        return 0
    except Exception as exc:
        message = re.sub(r"https?://[^\s\"']+|sk-[A-Za-z0-9]+|task_[A-Za-z0-9_-]+", "[REDACTED]", str(exc))
        message = re.sub(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", "[ID]", message)
        print(json.dumps({"case": current, "success": False, "error": type(exc).__name__, "message": message[:1500]}), flush=True)
        return 1
    finally:
        nodes.submit_3d_task, nodes.poll_3d_task = original_submit, original_poll


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm-live", action="store_true")
    parser.add_argument("--output", required=True)
    sys.exit(main(parser.parse_args()))
