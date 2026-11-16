"""Opt-in two-request chat acceptance with a persistent no-replay journal."""

import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import sys

import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
from ComfyUI_Seedance import nodes
from ComfyUI_Seedance.core import llm


def main(args):
    if not args.confirm_live or not os.getenv("SEEDANCE_API_KEY"):
        raise SystemExit("Requires --confirm-live and SEEDANCE_API_KEY")
    directory = Path(args.output).resolve()
    state_path = directory/"private_responses.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    proof_path = directory/"proof.json"
    proof = json.loads(proof_path.read_text()) if proof_path.exists() else []
    def persist():
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    with contextlib.redirect_stdout(io.StringIO()):
        config = nodes.get_config()
        models = llm.catalog(config, force=True)
    print(json.dumps({"catalog": "success", "llm_models": len(models), "source": llm.BASE_URL}), flush=True)
    current = ""
    def run(case, **kwargs):
        nonlocal current
        current = case
        if state.get(case, {}).get("result"):
            result = tuple(state[case]["result"])
        else:
            if case in state or len(state) >= 2:
                raise RuntimeError("Refusing to replay a previous or uncertain chat request")
            state[case] = {"started": True}
            persist()
            with contextlib.redirect_stdout(io.StringIO()):
                result = nodes.SeedanceLLMAPI().execute(model="qwen/qwen3.8-flash-next", api_config=config,
                    max_tokens=256, system_prompt="Answer concisely. Do not explain or reason.", **kwargs)["result"]
            state[case]["result"] = result
            persist()
        if not result[0].strip():
            raise RuntimeError("Chat returned an empty final answer")
        item = {"case": case, "success": True, "characters": len(result[0]), "history_messages": len(json.loads(result[2]))}
        proof[:] = [p for p in proof if p["case"] != case] + [item]
        proof_path.write_text(json.dumps(proof, indent=2), encoding="utf-8")
        print(json.dumps(item), flush=True)
        return result
    try:
        first = run("text", prompt="Reply with exactly READY.")
        image = torch.zeros(1, 64, 64, 3)
        image[..., 0] = 1
        image[:, :, 32:, 0] = 0
        image[:, :, 32:, 2] = 1
        second = run("vision_stream_history", prompt="What are the two main colors in this image? Reply with the two English color words only.",
                     image1=image, history=first[2], stream=True)
        if not all(color in second[0].lower() for color in ("red", "blue")):
            raise RuntimeError("Vision answer did not identify both fixture colors")
        print("PASS text, vision, streaming and history; exactly two synchronous chat requests", flush=True)
        return 0
    except Exception as error:
        print(json.dumps({"case": current, "success": False, "message": llm.safe_error(error, config)}), flush=True)
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm-live", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    directory = Path(args.output).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory/".live.lock"
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(descriptor)
    try:
        sys.exit(main(args))
    finally:
        lock.unlink(missing_ok=True)
