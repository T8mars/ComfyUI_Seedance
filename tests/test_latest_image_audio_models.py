import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import torch


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT.parent))

from ComfyUI_Seedance import concurrent_nodes, nodes
from ComfyUI_Seedance.core import client


CONFIG = {"base_url": "https://example.test", "api_key": "sk-test"}
IMAGE = torch.zeros((1, 8, 8, 3), dtype=torch.float32)
AUDIO = {"waveform": torch.zeros((1, 1, 100)), "sample_rate": 24000}


class LatestImageNodeTests(unittest.TestCase):
    def test_gk_v2_contract_and_execution(self):
        node = nodes.ZhenzhenImageGKV2()
        self.assertEqual(nodes.ZHENZHEN_IMAGE_GK_V2_MODEL, "zhenzhen-image-gk-v2")
        self.assertEqual(
            node._build_payload("clean studio portrait", "16:9", 2),
            {
                "model": "zhenzhen-image-gk-v2",
                "prompt": "clean studio portrait",
                "size": "16:9",
                "n": 2,
            },
        )
        final = {"data": {"status": "SUCCESS", "result_url": "https://result.test/a.png"}}
        with (
            patch.object(nodes, "get_config", return_value=CONFIG),
            patch.object(nodes, "submit_image_task", return_value="task-test") as submit,
            patch.object(nodes, "poll_image_task", return_value=final),
            patch.object(nodes, "extract_image_url", return_value="https://result.test/a.png"),
            patch.object(nodes, "download_image", return_value=IMAGE),
        ):
            result = node.execute(prompt="clean studio portrait", size="1:1", n=1)
        self.assertEqual(submit.call_args.args[0]["model"], "zhenzhen-image-gk-v2")
        self.assertTrue(torch.equal(result["result"][0], IMAGE))

    def test_wan_contract_separates_t2i_and_i2i(self):
        node = nodes.Wan27GlobalImage()
        self.assertEqual(nodes.WAN27_GLOBAL_IMAGE_MODELS, [
            "wan-2.7-global-t2i",
            "wan-2.7-global-i2i",
            "wan-2.7-global-i2i-pro",
        ])
        t2i = node._build_payload(
            nodes.WAN27_GLOBAL_T2I_MODEL,
            "minimal product photo",
            1024,
            1536,
            True,
            [],
        )
        self.assertEqual(t2i["metadata"], {
            "width": 1024,
            "height": 1536,
            "thinking_mode": True,
        })
        self.assertNotIn("images", t2i)

        urls = [f"https://media.test/{index}.png" for index in range(1, 10)]
        i2i = node._build_payload(
            nodes.WAN27_GLOBAL_I2I_PRO_MODEL,
            "edit all references",
            1024,
            1024,
            False,
            urls,
        )
        self.assertEqual(i2i["images"], urls)
        self.assertNotIn("metadata", i2i)

    def test_wan_i2i_uploads_connected_slots_in_order(self):
        final = {"data": {"status": "SUCCESS", "result_url": "https://result.test/a.png"}}
        with (
            patch.object(nodes, "get_config", return_value=CONFIG),
            patch.object(nodes, "upload_media", side_effect=["https://media.test/1.png", "https://media.test/3.png"]) as upload,
            patch.object(nodes, "submit_image_task", return_value="task-test") as submit,
            patch.object(nodes, "poll_image_task", return_value=final),
            patch.object(nodes, "extract_image_url", return_value="https://result.test/a.png"),
            patch.object(nodes, "download_image", return_value=IMAGE),
        ):
            nodes.Wan27GlobalImage().execute(
                model=nodes.WAN27_GLOBAL_I2I_MODEL,
                prompt="edit these references",
                width=1024,
                height=1024,
                thinking_mode=True,
                image1=IMAGE,
                image3=IMAGE,
            )
        self.assertEqual(upload.call_count, 2)
        self.assertEqual(submit.call_args.args[0]["images"], [
            "https://media.test/1.png",
            "https://media.test/3.png",
        ])


class LatestAudioNodeTests(unittest.TestCase):
    def test_audio_url_list_prefers_and_preserves_documented_array(self):
        response = {
            "data": {
                "result_url": "https://result.test/primary.mp3",
                "data": {
                    "content": {
                        "audio_urls": [
                            "https://result.test/one.mp3",
                            "https://result.test/two.mp3",
                            "https://result.test/two.mp3",
                        ]
                    }
                },
            }
        }
        self.assertEqual(client.extract_audio_urls(response), [
            "https://result.test/one.mp3",
            "https://result.test/two.mp3",
            "https://result.test/two.mp3",
        ])
        self.assertEqual(client.extract_audio_url(response), "https://result.test/one.mp3")

    def test_qwen_tts_payload_is_model_aware(self):
        node = nodes.Qwen3TTS()
        flash = node._build_payload(
            nodes.QWEN3_TTS_FLASH_MODEL,
            "你好，世界。",
            "Cherry",
            "Chinese",
            "快速而自然",
            True,
        )
        self.assertEqual(flash["metadata"], {
            "voice": "Cherry",
            "language_type": "Chinese",
        })
        instruct = node._build_payload(
            nodes.QWEN3_TTS_INSTRUCT_FLASH_MODEL,
            "你好，世界。",
            "Cherry",
            "Chinese",
            "快速而自然",
            True,
        )
        self.assertEqual(instruct["metadata"]["instructions"], "快速而自然")
        self.assertTrue(instruct["metadata"]["optimize_instructions"])

    def test_minimax_payloads_use_confirmed_gateway_types(self):
        node = nodes.MinimaxAudio()
        common = {
            "prompt": "soft ambient piano",
            "lyrics": "",
            "is_instrumental": True,
            "lyrics_optimizer": False,
            "voice_id": "Wise_Woman",
            "speed": 1.0,
            "volume": 1.0,
            "pitch": 0,
            "language_boost": "auto",
            "output_format": "mp3",
            "sample_rate": "32000",
            "bitrate": "128000",
            "channel": "1",
            "custom_voice_id": "SeedanceVoice01",
            "clone_target_model": nodes.MINIMAX_SPEECH_HD_MODEL,
            "need_noise_reduction": False,
            "need_volume_normalization": False,
        }
        music = node._build_payload({**common, "model": nodes.MINIMAX_MUSIC_MODEL})
        self.assertIs(music["metadata"]["is_instrumental"], True)
        self.assertEqual(music["metadata"]["sample_rate"], "32000")
        self.assertEqual(music["metadata"]["bitrate"], "128000")
        self.assertNotIn("lyrics", music["metadata"])

        speech = node._build_payload({**common, "model": nodes.MINIMAX_SPEECH_HD_MODEL})
        self.assertEqual(speech["metadata"]["voice_id"], "Wise_Woman")
        self.assertEqual(speech["metadata"]["vol"], 1.0)
        self.assertEqual(speech["metadata"]["channel"], 1)

        clone = node._build_payload(
            {**common, "model": nodes.MINIMAX_VOICE_CLONE_MODEL},
            "https://media.test/voice.wav",
        )
        self.assertEqual(clone["metadata"]["audio_url"], "https://media.test/voice.wav")
        self.assertEqual(clone["metadata"]["custom_voice_id"], "SeedanceVoice01")

    def test_mureka_downloads_every_ordered_result(self):
        final = {
            "data": {
                "status": "SUCCESS",
                "data": {"content": {"audio_urls": ["u1", "u2"]}},
            }
        }
        with (
            patch.object(nodes, "get_config", return_value=CONFIG),
            patch.object(nodes, "submit_audio_task", return_value="task-test") as submit,
            patch.object(nodes, "poll_audio_task", return_value=final),
            patch.object(nodes, "extract_audio_urls", return_value=["u1", "u2"]),
            patch.object(nodes, "download_audio", side_effect=[(AUDIO, "p1"), (AUDIO, "p2")]) as download,
        ):
            result = nodes.MurekaBGM().execute(
                model="mureka-v9-bgm",
                prompt="calm acoustic background music",
                instrumental_id="",
                n=2,
            )
        self.assertEqual(submit.call_args.args[0], {
            "model": "mureka-v9-bgm",
            "prompt": "calm acoustic background music",
            "metadata": {"n": 2, "stream": False},
        })
        self.assertEqual(download.call_count, 2)
        self.assertEqual(len(result["result"][0]), 2)
        self.assertEqual(json.loads(result["result"][1]), ["u1", "u2"])


class LatestModelRegistrationTests(unittest.TestCase):
    def test_nodes_and_image_concurrent_wrappers_are_registered(self):
        expected = {
            "Zhenzhen_Image_GK_V2": nodes.ZhenzhenImageGKV2,
            "Wan_2_7_Global_Image": nodes.Wan27GlobalImage,
            "Qwen3_TTS": nodes.Qwen3TTS,
            "Minimax_Audio": nodes.MinimaxAudio,
            "Mureka_BGM": nodes.MurekaBGM,
        }
        for key, node_class in expected.items():
            self.assertIs(nodes.NODE_CLASS_MAPPINGS[key], node_class)
        for key in ("Zhenzhen_Image_GK_V2", "Wan_2_7_Global_Image"):
            wrapper = concurrent_nodes.CONCURRENT_NODE_CLASS_MAPPINGS[
                f"SeedanceConcurrent_{key}_Submit"
            ]
            self.assertEqual(wrapper.CONCURRENT_KIND, "image")

    def test_dynamic_frontend_covers_new_model_specific_controls(self):
        source = (PLUGIN_ROOT / "web" / "js" / "latest_image_audio_ui.js").read_text(
            encoding="utf-8"
        )
        for fragment in (
            'const WAN_NODE_NAME = "Wan_2_7_Global_Image"',
            'const QWEN_TTS_NODE_NAME = "Qwen3_TTS"',
            'const MINIMAX_AUDIO_NODE_NAME = "Minimax_Audio"',
            'model.endsWith("-t2i")',
            'model === "qwen3-tts-instruct-flash"',
            'model === "minimax-voice-clone"',
            'setInputVisible(node, input, model === "minimax-voice-clone")',
            'from "./dynamic_widget_ui.js"',
            "originalSeedanceNodeName(nodeData.name)",
        ):
            self.assertIn(fragment, source)

    def test_every_new_model_has_a_safe_example_workflow(self):
        expected = set(
            [nodes.ZHENZHEN_IMAGE_GK_V2_MODEL]
            + nodes.WAN27_GLOBAL_IMAGE_MODELS
            + nodes.QWEN3_TTS_MODELS
            + nodes.MINIMAX_AUDIO_MODELS
            + nodes.MUREKA_BGM_MODELS
        )
        found = {}
        new_node_types = {
            "Zhenzhen_Image_GK_V2",
            "Wan_2_7_Global_Image",
            "Qwen3_TTS",
            "Minimax_Audio",
            "Mureka_BGM",
        }
        for path in (PLUGIN_ROOT / "examples").glob("*.json"):
            workflow = json.loads(path.read_text(encoding="utf-8"))
            for node in workflow.get("nodes", []):
                if node.get("type") not in new_node_types:
                    continue
                if node["type"] == "Zhenzhen_Image_GK_V2":
                    model = nodes.ZHENZHEN_IMAGE_GK_V2_MODEL
                else:
                    model = node["widgets_values"][0]
                found[model] = (path, workflow, node)

        self.assertEqual(set(found), expected)
        for model, (path, workflow, node) in found.items():
            with self.subTest(model=model, workflow=path.name):
                config = next(
                    item for item in workflow["nodes"]
                    if item["type"] == "Seedance_Config"
                )
                self.assertEqual(config["widgets_values"][1], "")
                raw = path.read_text(encoding="utf-8")
                self.assertNotRegex(raw, r"sk-[A-Za-z0-9]{12,}")
                self.assertNotRegex(raw, r'"task_[A-Za-z0-9_-]{6,}"')
                if model in nodes.WAN27_GLOBAL_I2I_MODELS:
                    incoming = [
                        link for link in workflow["links"]
                        if link[3] == node["id"] and link[5] == "IMAGE"
                    ]
                    self.assertEqual(len(incoming), 1)
                if model == nodes.MINIMAX_VOICE_CLONE_MODEL:
                    incoming = [
                        link for link in workflow["links"]
                        if link[3] == node["id"] and link[5] == "AUDIO"
                    ]
                    self.assertEqual(len(incoming), 1)


if __name__ == "__main__":
    unittest.main()
