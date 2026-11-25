"""Offline regression tests for Magi 2 and the two LLM additions."""

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
import ComfyUI_Seedance as plugin
from ComfyUI_Seedance import nodes
from ComfyUI_Seedance.core import llm, magi2
from ComfyUI_Seedance.core.client import SeedanceAPIError


def audio(seconds):
    return {"waveform": torch.zeros(1, 1, 8000 * seconds), "sample_rate": 8000}


IMAGE = torch.zeros(1, 8, 8, 3)
PROMPT = "A blue cube rotates slowly."
TASK_END = {"data": {"status": "SUCCESS", "result_url": "https://example.test/out.mp4"}}


class Magi2Tests(unittest.TestCase):
    def test_text_and_frame_mapping_for_both_models(self):
        for model in magi2.MODELS:
            body, _ = magi2.prepare(dict(model=model, prompt=PROMPT, seconds=4, seed=0, generate_audio=False))
            self.assertEqual(body, {"model": model, "prompt": PROMPT, "seconds": "4",
                "metadata": {"resolution": "1080p", "generate_audio": False, "seed": 0}})
            body, media = magi2.prepare(dict(model=model, prompt=PROMPT, generation_type="frame",
                                             image2=IMAGE, image1=IMAGE, ratio="9:16", seconds=30))
            self.assertEqual(body["metadata"]["generation_type"], "frame")
            self.assertEqual(body["metadata"]["ratio"], "9:16")
            self.assertEqual([(field, name) for field, name, _, _ in media],
                             [("images", "magi_image1.png"), ("images", "magi_image2.png")])
            body, _ = magi2.prepare(dict(model=model, prompt=PROMPT, image1=IMAGE))
            self.assertNotIn("ratio", body["metadata"])
            self.assertNotIn("generation_type", body["metadata"])

    def test_reference_mode_allows_one_image_and_auto_allows_three(self):
        body, media = magi2.prepare({"prompt": PROMPT, "generation_type": "reference", "image1": IMAGE})
        self.assertEqual(body["metadata"]["generation_type"], "reference")
        self.assertEqual(len(media), 1)
        _, media = magi2.prepare({"prompt": PROMPT, "image1": IMAGE, "image2": IMAGE, "image3": IMAGE})
        self.assertEqual(len(media), 3)

    def test_failure_before_any_network_and_linked_prompt_validation(self):
        self.assertIs(nodes.Magi2Video.VALIDATE_INPUTS(), True)
        self.assertIs(nodes.Magi2Video.VALIDATE_INPUTS(generation_type="frame"), True)
        invalid = [
            {"prompt": ""}, {"prompt": "x" * 15001}, {"model": "magi-next"},
            {"generation_type": "text", "image1": IMAGE}, {"generation_type": "frame"},
            {"generation_type": "frame", "image2": IMAGE},
            {"generation_type": "frame", "image1": IMAGE, "image2": IMAGE, "image3": IMAGE},
            {"generation_type": "frame", "image1": IMAGE, "audio1": audio(2)},
            {"generation_type": "reference"}, {"seconds": 3}, {"seconds": 31}, {"seconds": "4"},
            {"seed": -1}, {"seed": 2147483648}, {"seed": True}, {"ratio": "2:3"},
            {"image11": IMAGE}, {"video6": object()}, {"audio6": audio(2)},
            {"image1": torch.zeros(2, 8, 8, 3)}, {"audio1": audio(1)},
            {"audio1": audio(31)}, {"audio1": audio(15), "audio2": audio(16)},
        ]
        with patch.object(nodes, "upload_media") as upload, patch.object(nodes, "submit_legacy_video_task") as post:
            for values in invalid:
                with self.subTest(fields=values.keys()), self.assertRaises(SeedanceAPIError):
                    nodes.Magi2Video().execute(**{"prompt": PROMPT, **values})
            upload.assert_not_called()
            post.assert_not_called()

    def test_mixed_reference_caps_and_combined_duration(self):
        values = {"prompt": PROMPT, **{f"image{i}": IMAGE for i in range(1, 11)},
                  **{f"video{i}": f"video{i}" for i in range(1, 6)},
                  **{f"audio{i}": audio(6) for i in range(1, 6)}}
        with patch.object(magi2, "video_to_bytes", return_value=(b"video", "mp4")), \
                patch.object(magi2, "probe_video", return_value={"duration": 6}) as probe:
            _, media = magi2.prepare(values)
            self.assertEqual([field for field, *_ in media], ["images"] * 10 + ["video_url"] * 5 + ["audio_urls"] * 5)
            for invalid in (1.99, 6.01, 30.01, float("nan")):
                probe.return_value = {"duration": invalid}
                with self.subTest(invalid=invalid), self.assertRaises(SeedanceAPIError):
                    magi2.prepare(values)

    def test_shared_upload_then_only_legacy_submit_poll_download(self):
        image_url, video_url, audio_url = ["https://example.test/" + name for name in ("image.png", "in.mp4", "in.wav")]
        result_video = object()
        with patch.object(magi2, "video_to_bytes", return_value=(b"video", "mp4")), \
                patch.object(magi2, "probe_video", return_value={"duration": 2}), \
                patch.object(nodes, "get_config", return_value={}), \
                patch.object(nodes, "upload_media", side_effect=[image_url, video_url, audio_url]), \
                patch.object(nodes, "submit_legacy_video_task", return_value="fake-task") as post, \
                patch.object(nodes, "poll_legacy_video_task", return_value=TASK_END) as poll, \
                patch.object(nodes, "download_video", return_value=result_video) as download:
            result = nodes.Magi2Video().execute(model="magi-2-global", generation_type="reference", prompt=PROMPT,
                                                image1=IMAGE, video1=object(), audio1=audio(2))["result"]
        self.assertEqual(result[:3], (result_video, "https://example.test/out.mp4", "fake-task"))
        body = post.call_args.args[0]
        self.assertEqual(body["images"], [image_url])
        self.assertEqual(body["metadata"]["video_url"], [video_url])
        self.assertEqual(body["metadata"]["audio_urls"], [audio_url])
        self.assertEqual(poll.call_args.args[0], "fake-task")
        self.assertEqual(download.call_args.args[0], result[1])

    def test_concurrent_schema_and_seed(self):
        cls = plugin.NODE_CLASS_MAPPINGS["SeedanceConcurrent_Magi_2_Video_Submit"]
        self.assertFalse(hasattr(cls, "VALIDATE_INPUTS"))
        self.assertEqual(cls.INPUT_TYPES(), nodes.Magi2Video.INPUT_TYPES())
        seed = cls.INPUT_TYPES()["required"]["seed"][1]
        self.assertEqual(seed["max"], 2147483647)
        self.assertTrue(seed["control_after_generate"])


class WorkflowTests(unittest.TestCase):
    def test_all_eight_examples_have_blank_keys_and_correct_ports(self):
        known = {f"{model}-{suffix}.json": (model, mode, refs)
                 for model in magi2.MODELS
                 for suffix, mode, refs in (("t2v", "text", []), ("i2v", "frame", ["image1", "image2"]),
                                            ("r2v", "reference", ["image1", "video1", "audio1"]))}
        known.update({"moonshotai-kimi-k3.1-pro-text.json": ("moonshotai/kimi-k3.1-pro", None, []),
                      "zhenzhen-gk-4.7-vision.json": ("zhenzhen/gk-4.7", None, ["image1"])})
        for name, (model, mode, refs) in known.items():
            with self.subTest(name=name):
                doc = json.loads((ROOT / "examples" / name).read_text(encoding="utf-8"))
                graph = {node["id"]: node for node in doc["nodes"]}
                target = next(n for n in graph.values() if n["type"] in ("Magi_2_Video", "Seedance_LLM_API"))
                config = next(n for n in graph.values() if n["type"] == "Seedance_Config")
                self.assertEqual(config["widgets_values"], [llm.BASE_URL, ""])
                self.assertEqual(target["widgets_values"][0], model)
                if mode:
                    self.assertEqual(target["widgets_values"][1], mode)
                else:
                    self.assertIn(model, llm.MODELS)
                self.assertEqual([i["name"] for i in target["inputs"] if i["link"] is not None and i["name"] != "api_config"], refs)
                for id_, src, out, dst, inp, type_ in doc["links"]:
                    self.assertEqual(graph[dst]["inputs"][inp]["link"], id_)
                    self.assertIn(id_, graph[src]["outputs"][out]["links"])
                    self.assertEqual(graph[src]["outputs"][out]["type"], type_)


if __name__ == "__main__":
    unittest.main()
